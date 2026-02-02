# Finding Bugs in Open Source Python APIs with Static Exception Flow Analysis

*We built a tool that found real bugs in httpbin, Sentry, Airflow, Superset, and Label Studio - including one you can trigger right now*

---

## The Problem: APIs Should Never 500

Every Python web developer has seen it: a user triggers some edge case, an exception bubbles up unhandled, and your API returns a generic "Internal Server Error" with a 500 status code.

The user has no idea what went wrong. Your logs have a stack trace, but by the time you investigate, the context is lost. And somewhere, a customer is frustrated.

**The goal is simple: APIs should return meaningful errors, not crash.**

But in large codebases, ensuring every exception is properly handled is nearly impossible to verify manually. You can't grep for "what exceptions can reach this endpoint" - it requires understanding the entire call graph.

---

## Try It Now: A Live Bug in httpbin.org

Before diving into the technical details, here's a bug you can trigger right now. httpbin is a popular HTTP testing service used by developers worldwide. Our tool found an unhandled `ValueError` in its digest authentication endpoint.

**First, here's a normal failed authentication (wrong credentials, valid format):**

```bash
curl -i -H 'Authorization: Digest username="user", realm="test", nonce="abc", uri="/digest-auth/auth/user/passwd", qop=auth, nc=00000001, cnonce="xyz", response="wrong"' \
  'https://httpbin.org/digest-auth/auth/user/passwd'
```

```
HTTP/2 401
www-authenticate: Digest realm="me@kennethreitz.com", nonce="...", qop="auth", ...
```

That's correct - bad credentials get `401 Unauthorized`.

**Now change `qop=auth` to `qop=INVALID`:**

```bash
curl -i -H 'Authorization: Digest username="user", realm="test", nonce="abc", uri="/digest-auth/auth/user/passwd", qop=INVALID, nc=00000001, cnonce="xyz", response="wrong"' \
  'https://httpbin.org/digest-auth/auth/user/passwd'
```

```
HTTP/2 500

<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 3.2 Final//EN">
<title>500 Internal Server Error</title>
<h1>Internal Server Error</h1>
```

The only difference is `qop=INVALID` instead of `qop=auth`. Same endpoint, same structure, but the server crashes.

**Is this a real bug?** Yes. [RFC 7616](https://datatracker.ietf.org/doc/html/rfc7616) (HTTP Digest Authentication) is explicit: *"If a parameter or its value is improper, or required parameters are missing, the proper response is a 4xx error code."* A 500 Internal Server Error violates the spec and leaks implementation details.

**The code:** When the `qop` parameter has an unexpected value (not `auth`, `auth-int`, or empty), the code raises a `ValueError` that nobody catches:

```python
# httpbin/helpers.py:308
def HA2(credentials, request, algorithm):
    if credentials.get("qop") == "auth" or credentials.get('qop') is None:
        return H(...)
    elif credentials.get("qop") == "auth-int":
        return H(...)
    raise ValueError  # <-- Uncaught! Becomes 500 error
```

Our tool traced this exception from line 308, through `response()`, through `check_digest_auth()`, all the way up to the `/digest-auth` route handler - and found no `try/except` along the way.

This is exactly the kind of bug that's hard to find manually but trivial for static analysis.

---

## The Approach: Static Exception Flow Analysis

We built a tool that:

1. **Parses every Python file** in a codebase using libcst
2. **Builds a call graph** - who calls whom
3. **Identifies raise sites** - where exceptions are thrown
4. **Identifies catch sites** - where exceptions are caught
5. **Propagates exceptions** through the call graph to find what escapes

The key insight: this is a fixpoint computation. If function A raises `ValueError` and function B calls A without catching it, then B can also "raise" `ValueError`. Repeat until stable.

---

## The Results: Real Bugs in Production Code

We ran the tool on five open source projects:

| Project | Framework | Files | Time | Endpoints | With Issues |
|---------|-----------|-------|------|-----------|-------------|
| **httpbin** | Flask | 8 | 0.8s | 55 | 1 (2%) |
| **Sentry** | Django/DRF | 7,469 | 87s | 52 | 43 (83%)* |
| **Airflow** | FastAPI | 2,847 | 45s | 122 | 5 (4%) |
| **Superset** | Flask | 1,129 | 27s | 251 | 133 (53%)** |
| **Label Studio** | Django/DRF | 847 | 18s | 156 | 3 (2%) |

*Sentry uses Django REST Framework which auto-handles `APIException` subclasses. We configured the tool to filter these out (see config below), reducing false positives from 258 to 0.

**Superset uses global Flask error handlers that catch all exceptions, making most flagged issues false positives. See discussion below.

### Case Study: Sentry

Sentry is a 7,469-file Python codebase with 52 Django REST Framework endpoints. Running the analysis:

```bash
git clone https://github.com/getsentry/sentry /tmp/sentry
bubble django audit -d /tmp/sentry
```

**Raw output**: 43 endpoints with issues, but many are false positives (DRF handles `APIException` subclasses automatically).

**With configuration** (`.flow/config.yaml`):
```yaml
handled_base_classes:
  - rest_framework.exceptions.APIException
  - sentry.api.exceptions.SentryAPIException
async_boundaries:
  - "*.apply_async"
  - "*.delay"
```

This filters out 258 false positives, leaving real issues.

#### Bug #1: Email Validation Inconsistency

**Call path**:
```
POST /api/0/users/{user_id}/emails/
  → UserEmailsEndpoint.post()
    → add_email(email, user)
      → raise InvalidEmailError  # NOT CAUGHT!
```

**Code**: [src/sentry/users/api/endpoints/user_emails.py:45](https://github.com/getsentry/sentry/blob/master/src/sentry/users/api/endpoints/user_emails.py#L45)
```python
def add_email(email: str, user: User) -> UserEmail:
    if email is None:
        raise InvalidEmailError  # ← Not caught!
    # ...
    if UserEmail.objects.filter(...).exists():
        raise DuplicateEmailError  # ← This one IS caught!
```

**The inconsistency** ([line 154](https://github.com/getsentry/sentry/blob/master/src/sentry/users/api/endpoints/user_emails.py#L154)):
```python
except DuplicateEmailError:
    return self.respond({"detail": "Email already associated"}, status=409)
# InvalidEmailError NOT in except clause → 500!
```

**Reproduce**:
```bash
bubble raises InvalidEmailError -d /tmp/sentry
# Shows 2 raise sites at lines 45 and 70

bubble catches InvalidEmailError -d /tmp/sentry
# Shows only generic "except Exception" handlers, not specific catch
```

**What users see**: 500 Internal Server Error
**What they should see**: "Invalid email address" (400) - like `DuplicateEmailError` gets a proper 409

#### Bug #2: OAuth Misconfiguration

**Call path**:
```
GET /extensions/github/setup/
  → OAuth2LoginView.dispatch()
    → OAuth2Provider.get_pipeline_views()
      → get_oauth_client_id()
        → _get_oauth_parameter("client_id")
          → raise KeyError("Unable to resolve OAuth parameter 'client_id'")
```

**Code**: [src/sentry/identity/oauth2.py:103](https://github.com/getsentry/sentry/blob/master/src/sentry/identity/oauth2.py#L103)
```python
def _get_oauth_parameter(self, parameter_name):
    # ... check class property, config, provider_model ...
    raise KeyError(f'Unable to resolve OAuth parameter "{parameter_name}"')
```

**Reproduce**:
```bash
bubble raises KeyError -d /tmp/sentry | grep oauth2
# src/sentry/identity/oauth2.py:103  in _get_oauth_parameter()
```

**What users see**: 500 on self-hosted Sentry when clicking "Connect GitHub"
**What they should see**: "GitHub integration not configured. Check GITHUB_APP_ID in settings."

### Superset: A Well-Engineered Codebase

Superset demonstrates **good exception handling practices**. Our tool initially flagged 133 endpoints, but investigation revealed comprehensive error handling:

**Global Flask error handlers** ([superset/views/error_handling.py](https://github.com/apache/superset/blob/master/superset/views/error_handling.py)):
```python
@app.errorhandler(SupersetException)
def show_superset_error(ex):
    return json_error_response(ex.message, status=ex.status)

@app.errorhandler(Exception)
def show_unexpected_exception(ex):
    return json_error_response(ex.message, status=500)  # Catch-all
```

**Well-designed exception hierarchy** with HTTP status codes baked in:
```python
class SupersetException(Exception):
    status = 500  # Default

class QueryNotFoundException(SupersetException):
    status = 404  # Specific code

class QueryObjectValidationError(SupersetException):
    status = 400  # Validation errors
```

**What this means**: Superset won't crash with unhandled exceptions. The global handlers catch everything. However, validation using `ValueError` instead of `SupersetException` subclasses will return 500 with a generic message rather than 400 with a specific message - a usability issue, not a crash.

**Lesson**: This is what good error handling looks like. The tool's value here is identifying endpoints that could benefit from more specific exception types, not finding crashes

### Airflow: Multiple Uncaught Exceptions in FastAPI Routes

Airflow recently migrated to **FastAPI** for its web API. Running our generic detector against its 122 FastAPI endpoints:

```bash
bubble fastapi audit -d /tmp/airflow/airflow-core/src/airflow/api_fastapi/
```

**Results**: 5 routes with exception handling issues, 117 routes fully covered.

#### Bug #1: TypeError in Asset Expression Parsing

**Call path**:
```
GET /structure_data
  → structure_data()           routes/ui/structure.py:52
    → get_upstream_assets()    services/ui/structure.py:37
      → raise TypeError        services/ui/structure.py:69
```

**Code**: [services/ui/structure.py:69](https://github.com/apache/airflow/blob/main/airflow-core/src/airflow/api_fastapi/core_api/services/ui/structure.py#L69)
```python
    if nested_expr_key in ("any", "all"):
        nested_expression = expr
    elif nested_expr_key in ("asset", "alias", "asset-name-ref", "asset-uri-ref"):
        asset_info = expr[nested_expr_key]
    else:
        raise TypeError(f"Unsupported type: {expr.keys()}")
    ```
    
    **The route handler** has no try/except:
    ```python
    if (asset_expression := serialized_dag.dag_model.asset_expression) and entry_node_ref:
        upstream_asset_nodes, upstream_asset_edges = get_upstream_assets(
            asset_expression, entry_node_ref["id"]
        )  # No exception handling!
    ```
    
    **Exception handlers checked**: Airflow's core_api only registers handlers for `IntegrityError` and `DeserializationError` ([exceptions.py:121](https://github.com/apache/airflow/blob/main/airflow-core/src/airflow/api_fastapi/common/exceptions.py#L121)). No handler for `TypeError`.
    
    **Confirmed**: This is a real bug. A DAG with an unexpected asset expression key triggers a 500 error.
    
    #### Bug #2: RuntimeError from Uninitialized Auth Manager
    
    **Call path** (affects 6 routes including `/auth/menus`, `/{import_error_id}`):
    ```
    GET /auth/menus
    → get_auth_menus()           routes/ui/auth.py:32
        → get_auth_manager()       app.py:158
        → raise RuntimeError     app.py:161
    ```
    
    **Code**: [app.py:158-165](https://github.com/apache/airflow/blob/main/airflow-core/src/airflow/api_fastapi/app.py#L158)
    ```python
    def get_auth_manager() -> BaseAuthManager:
        """Return the auth manager, provided it's been initialized before."""
        if _AuthManagerState.instance is None:
            raise RuntimeError(
                "Auth Manager has not been initialized yet. "
                "The `init_auth_manager` method needs to be called first."
            )
        return _AuthManagerState.instance
    ```
    
    **Exception handlers checked**: No handler for `RuntimeError` in core_api.
    
    **Confirmed**: Real bug. If auth manager initialization fails or is skipped, multiple routes return 500 with a stack trace instead of a meaningful error.
    
    #### Bug #3: ValueError in Task Instance Run
    
    **Call path**:
    ```
    PATCH /{task_instance_id}/run
    → ti_run()                   execution_api/routes/task_instances.py:101
        → (database lookup)
        → raise ValueError       execution_api/routes/task_instances.py:226
    ```
    
    **Code**: [task_instances.py:224-226](https://github.com/apache/airflow/blob/main/airflow-core/src/airflow/api_fastapi/execution_api/routes/task_instances.py#L224)
    ```python
    if not dr:
        log.error("DagRun not found", dag_id=ti.dag_id, run_id=ti.run_id)
        raise ValueError(f"DagRun with dag_id={ti.dag_id} and run_id={ti.run_id} not found.")
    ```
    
    **Exception handlers checked**: The route catches `SQLAlchemyError` (line 268) but not `ValueError`. The execution_api has a generic `Exception` handler that returns a 500 with "Internal server error".
    
    **Confirmed**: Real bug. A database consistency issue (TaskInstance exists but DagRun doesn't) returns a generic 500 instead of a specific 404.

#### Airflow's Exception Handling Architecture

Airflow has **two sub-applications** with different handler strategies:

| Sub-app | Generic Handler | Behavior |
|---------|-----------------|----------|
| `core_api` | None | Unhandled exceptions → raw 500 |
| `execution_api` | `@app.exception_handler(Exception)` | Unhandled exceptions → 500 with "Internal server error" |

Neither converts `TypeError`, `ValueError`, or `RuntimeError` to proper HTTP responses. The `execution_api` at least logs the exception, but users still see a generic 500.

#### Evidence of Inconsistency

The bugs are real because we can see inconsistent patterns within the same codebase:

| Service Layer | Exception | Route catches it? |
|---------------|-----------|-------------------|
| `dependencies.py:65` | `ValueError` | **Yes** ✓ → `HTTPException(404)` |
| `calendar.py:292,301` | `ValueError` | **No** ✗ → 500 |
| `structure.py:69,102` | `TypeError` | **No** ✗ → 500 |

The `dependencies.py` route handler follows the correct pattern:
```python
try:
    data = extract_single_connected_component(node_id, data["nodes"], data["edges"])
except ValueError as e:
    raise HTTPException(404, str(e))
```

But `structure.py` and `calendar.py` don't wrap their service calls:
```python
upstream_asset_nodes, upstream_asset_edges = get_upstream_assets(
    asset_expression, entry_node_ref["id"]
)
```

**Lesson**: These are genuine oversights, not design decisions. One developer got it right, others didn't follow the same pattern

### Case Study: Label Studio

Label Studio is a popular open-source data labeling platform with 156 Django REST Framework endpoints. Our analysis found 3 real bugs - all cases where exception handling is inconsistent with patterns used elsewhere in the same codebase.

```bash
git clone https://github.com/HumanSignal/label-studio /tmp/label-studio
bubble django audit -d /tmp/label-studio/label_studio
```

#### Bug #1: DataManagerException Inherits from Exception (Not APIException)

**Location**: `data_manager/functions.py:21-22`

```python
class DataManagerException(Exception):
    pass
```

This exception is raised in 5 places across the Data Manager API for validation errors like "Project and View mismatch" and "selectedItems must be JSON encoded string." Since it inherits from Python's base `Exception` instead of DRF's `APIException`, all these errors become 500 Internal Server Errors.

**Call path**:
```
POST /api/dm/actions?id=propagate_annotations&project=1
  → ProjectActionsAPI.post()              data_manager/api.py:690
    → perform_action()                    data_manager/actions/__init__.py:133
      → propagate_annotations()           data_manager/actions/experimental.py:21
        → raise DataManagerException      # NOT CAUGHT → 500!
```

**Evidence this is a bug**: Label Studio *already has* a proper base exception class:

```python
class LabelStudioAPIException(APIException):
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    default_detail = 'Unknown error'
```

And other exceptions **do** use it correctly:

```python
class AnnotationDuplicateError(LabelStudioAPIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = 'Annotation with this unique id already exists'
```

**The fix**: Change `DataManagerException(Exception)` to `DataManagerException(LabelStudioAPIException)` with `status_code = 400`.

#### Bug #2 & #3: Storage Sync Endpoints Missing Exception Handling

**Location**: `io_storages/api.py:129-138`

```python
def post(self, request, *args, **kwargs):
    storage = self.get_object()
    storage.validate_connection()  # KeyError can escape here!
    storage.sync()
    ...
```

When S3/Azure/GCS validation fails (bucket not found, wrong prefix), a `KeyError` escapes as a 500. The `validate_connection()` method explicitly raises `KeyError`:

```python
if (keycount := result.get('KeyCount')) is None or keycount < expected_keycount:
    raise KeyError(f'{self.url_scheme}://{self.bucket}/{self.prefix} not found.')
```

**Affected endpoints** (10 total across all storage providers):

| Provider | Import Sync | Export Sync |
|----------|-------------|-------------|
| S3 | `POST /api/storages/s3/{id}/sync` | `POST /api/storages/export/s3/{id}/sync` |
| Azure | `POST /api/storages/azure/{id}/sync` | `POST /api/storages/export/azure/{id}/sync` |
| GCS | `POST /api/storages/gcs/{id}/sync` | `POST /api/storages/export/gcs/{id}/sync` |
| Redis | `POST /api/storages/redis/{id}/sync` | `POST /api/storages/export/redis/{id}/sync` |
| LocalFiles | `POST /api/storages/localfiles/{id}/sync` | `POST /api/storages/export/localfiles/{id}/sync` |

**Evidence this is a bug**: The exact same `validate_connection()` call IS properly wrapped in three other places:

```python
def perform_create(self, serializer):
    instance = serializer.Meta.model(**serializer.validated_data)
    try:
        instance.validate_connection()
    except Exception as exc:
        raise ValidationError(exc)
```

**Side-by-side comparison**:

| Operation | Exception Handling | HTTP Response |
|-----------|-------------------|---------------|
| Create export storage | `try/except → ValidationError` | 400 |
| Validate storage | `try/except → ValidationError` | 400 |
| **Sync storage** | **NONE** | **500** |

**The fix**: Add the same try/except wrapper to the sync endpoints.

---

## The Technical Journey

### Challenge 1: Python is Dynamic

Python doesn't have static types for exceptions. You can't declare `throws ValueError` like in Java. So we built resolution heuristics:

- **Import resolution**: `from foo import bar` → `bar()` resolves to `foo.bar`
- **Self-method resolution**: Inside `class Foo`, `self.method()` resolves to `Foo.method`
- **Constructor tracking**: `x = Foo(); x.bar()` resolves to `Foo.bar`
- **Name-based fallback**: If all else fails, match by function name

This gives us ~80% resolution accuracy, enough to find real bugs.

### Challenge 2: Scale

Sentry has 7,469 Python files and 134,516 call sites. Naive fixpoint iteration would take 20+ minutes.

We optimized:
- **Memoized fallback lookups**: 2.7x speedup
- **Skip evidence tracking for audits**: 4.3x speedup
- **ProcessPoolExecutor for extraction**: Full CPU utilization

Result: Full Sentry analysis in 87 seconds.

### Challenge 3: False Positives

Not every exception is a bug. Django REST Framework's `APIException` subclasses are automatically handled. We learned to recognize:

- **Framework-handled exceptions**: `ResourceDoesNotExist` → 404 (not a bug)
- **Generic handlers**: `except Exception` catches everything (flags as warning)
- **CLI vs Web**: Same codebase, different execution contexts

### Challenge 4: Framework Proliferation

Every web framework has its own decorator patterns:

| Framework | Route Decorator | Method Source |
|-----------|-----------------|---------------|
| Flask | `@app.route("/path", methods=["GET"])` | `methods` kwarg |
| FastAPI | `@router.get("/path")` | Decorator name |
| Django | `@api_view(["GET"])` | First argument |
| Flask-AppBuilder | `@expose("/path")` | `methods` kwarg |

Initially, we wrote separate detector classes for each framework (~500 lines across 3 files). But when we needed to add Airflow support, we realized the logic was identical - only the configuration differed.

**The insight**: Framework detection is just pattern matching. We replaced framework-specific code with a generic, configuration-driven detector:

```python
FASTAPI_CONFIG = FrameworkConfig(
    name="fastapi",
    route_patterns=[
        DecoratorRoutePattern(
            decorator_pattern="get",
            path_source="arg[0]",
            method_source="decorator_name",
        ),
        DecoratorRoutePattern(
            decorator_pattern="post",
            path_source="arg[0]",
            method_source="decorator_name",
        ),
    ],
    handler_patterns=[
        HandlerPattern(decorator_pattern="exception_handler"),
        HandlerPattern(call_pattern="*.add_exception_handler"),
    ],
)
```

**Result**: ~280 lines of generic code replaced ~500 lines of framework-specific code. Adding a new framework takes minutes - just define another config.

**The Airflow test**: We didn't need an Airflow-specific integration at all. Airflow uses standard FastAPI decorators (`@router.get`, `@router.post`), so `bubble fastapi audit` worked out of the box. This is the real payoff of the generic approach - if a framework uses the same patterns as an existing config, you don't need new code.

**Claude as integrator**: We used Claude to identify the patterns across frameworks and design the configuration schema. The conversation went:

> "These framework detectors look almost identical. The only differences are decorator names and where to find the path/method. Can we make this configuration-driven?"

Claude analyzed the existing Flask, FastAPI, and Django detectors, identified the common abstractions (`DecoratorRoutePattern`, `ClassRoutePattern`, `HandlerPattern`), and generated the generic implementation. This is a pattern we've found valuable: use AI to identify duplication, design the abstraction, and generate the unified implementation.

### Challenge 5: External Library Exceptions

Static analysis only sees your code. When you call `requests.get()`, we don't know it can raise `ConnectionError`, `Timeout`, or `HTTPError` - that information lives in the `requests` library source code.

**Solution: Exception stubs** - YAML files that declare what external functions can raise:

```yaml
# .flow/stubs/requests.yaml
module: requests

functions:
  get:
    - requests.exceptions.ConnectionError
    - requests.exceptions.Timeout
    - requests.exceptions.HTTPError
    - requests.exceptions.RequestException

  post:
    - requests.exceptions.ConnectionError
    - requests.exceptions.Timeout
    - requests.exceptions.HTTPError
    - requests.exceptions.RequestException
```

**Built-in stubs** ship with the tool for common libraries:
- `requests` - HTTP client exceptions
- `httpx` - Async HTTP client exceptions
- `boto3` - AWS SDK exceptions
- `redis` - Redis client exceptions
- `sqlalchemy` - Database exceptions

**User-defined stubs** go in `.flow/stubs/` for your specific dependencies:

```yaml
# .flow/stubs/stripe.yaml
module: stripe

functions:
  Charge.create:
    - stripe.error.CardError
    - stripe.error.RateLimitError
    - stripe.error.APIConnectionError
```

This lets the tool trace exceptions from external calls through your code to HTTP endpoints:

```
POST /checkout
  → create_payment()
    → stripe.Charge.create()  # ← Stub says: can raise CardError
      → CardError escapes!    # ← Now we know to catch this
```

---

## What We Learned

### 1. Generic `except Exception` is a Code Smell

All three codebases have patterns like:
```python
try:
    do_something()
except Exception:
    logger.error("Something went wrong")
    return generic_error()
```

This catches *everything*, including bugs that should crash. It masks real errors and gives users no useful feedback.

### 2. Validation Errors Shouldn't Be 500s

We found dozens of `ValueError` and `TypeError` exceptions used for validation that escape to become 500 errors. These should be caught and converted to 400 Bad Request with helpful messages.

### 3. External Service Errors Need Wrapping

Calls to external APIs (Google Cloud, Databricks, Slack) raise their own exceptions (`HTTPError`, `ApiError`). These escape as 500s when they should be wrapped with user-friendly messages.

---

## Try It Yourself

The tool is open source: [github.com/ianm199/flow](https://github.com/ianm199/flow)

```bash
# Install
pip install bubble-analysis

# Audit a Flask project
bubble flask audit -d /path/to/your/project

# Audit a Django/DRF project
bubble django audit -d /path/to/your/project

# Find where a specific exception is raised
bubble raises ValueError -d /path/to/your/project

# Trace what can escape from a function
bubble escapes my_function -d /path/to/your/project
```

**For large DRF codebases**, create `.flow/config.yaml` to filter framework-handled exceptions:

```yaml
handled_base_classes:
  - rest_framework.exceptions.APIException

async_boundaries:
  - "*.apply_async"  # Celery tasks
  - "*.delay"
```

This eliminates false positives from exceptions that DRF automatically converts to proper HTTP responses.

---

## Conclusion

Static analysis for exception flow is surprisingly tractable in Python. Despite the dynamic nature of the language, we can build useful call graphs and find real bugs.

The five projects we analyzed demonstrate a spectrum of exception handling practices:

- **httpbin**: A small codebase with a real, reproducible bug you can trigger right now
- **Sentry**: A large, complex codebase with genuine inconsistencies (some exceptions caught, similar ones not)
- **Superset**: An example of good practices - comprehensive global handlers and a well-designed exception hierarchy
- **Airflow**: A FastAPI-based API with real bugs in 5 of 122 routes - including `TypeError` from malformed asset expressions, `RuntimeError` from uninitialized auth manager, and `ValueError` from database inconsistencies
- **Label Studio**: A Django/DRF project where the correct exception patterns exist but aren't used consistently - `DataManagerException` should extend `APIException`, and storage sync endpoints need the same try/except wrapper used in storage creation

**The common thread**: Every bug we found exists alongside the correct pattern *in the same codebase*. These aren't design decisions - they're oversights. One developer got it right, another didn't follow the same pattern. Static analysis catches these inconsistencies systematically.

The tool's value isn't just finding bugs - it's also validating that exception handling is comprehensive. Superset's results show what "clean" looks like, while Sentry, Airflow, and Label Studio show where validation errors slip through as 500s.

Tools like this make it possible to systematically verify exception handling across an entire codebase, turning "I hope we handle all the errors" into "I know we handle all the errors."

---

*Built with libcst, ProcessPoolExecutor, and a lot of fixpoint iteration.*
