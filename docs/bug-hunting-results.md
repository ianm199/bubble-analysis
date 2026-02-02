# Bug Hunting Results - Static Exception Flow Analysis

This document captures all bugs found across open source Python projects using the bubble static analysis tool.

---

## Projects Analyzed

| Project | Framework | Endpoints | Real Bugs | Analysis Date |
|---------|-----------|-----------|-----------|---------------|
| httpbin | Flask | 55 | 1 | 2026-02-02 |
| Sentry | Django/DRF | 52 | 2 | 2026-02-02 |
| Airflow | FastAPI | 122 | 5 | 2026-02-02 |
| Superset | Flask | 251 | 0 (good practices) | 2026-02-02 |
| Label Studio | Django/DRF | 156 | 3 | 2026-02-02 |
| Redash | Flask-RESTful | 135 | 3 | 2026-02-02 |
| Datasette | ASGI/Custom | ~50 | 0 (well-written) | 2026-02-02 |

---

## httpbin

### Bug: ValueError in Digest Authentication (LIVE REPRODUCIBLE)

**Severity**: Medium
**File**: `httpbin/helpers.py:308`
**Endpoint**: `GET /digest-auth/auth/{user}/{passwd}`

**The Bug**:
```python
def HA2(credentials, request, algorithm):
    if credentials.get("qop") == "auth" or credentials.get('qop') is None:
        return H(...)
    elif credentials.get("qop") == "auth-int":
        return H(...)
    raise ValueError  # <-- Uncaught! Becomes 500 error
```

**Reproduction** (works on live httpbin.org):
```bash
# Normal request (401 Unauthorized - correct)
curl -i -H 'Authorization: Digest username="user", realm="test", nonce="abc", uri="/digest-auth/auth/user/passwd", qop=auth, nc=00000001, cnonce="xyz", response="wrong"' \
  'https://httpbin.org/digest-auth/auth/user/passwd'

# With invalid qop (500 Internal Server Error - BUG)
curl -i -H 'Authorization: Digest username="user", realm="test", nonce="abc", uri="/digest-auth/auth/user/passwd", qop=INVALID, nc=00000001, cnonce="xyz", response="wrong"' \
  'https://httpbin.org/digest-auth/auth/user/passwd'
```

**Evidence of Bug**: RFC 7616 explicitly states improper parameters should return 4xx, not 500.

---

## Sentry

### Bug 1: InvalidEmailError Not Caught

**Severity**: Medium
**File**: `src/sentry/users/api/endpoints/user_emails.py:45`
**Endpoint**: `POST /api/0/users/{user_id}/emails/`

**The Bug**:
```python
def add_email(email: str, user: User) -> UserEmail:
    if email is None:
        raise InvalidEmailError  # ← Not caught!
    # ...
    if UserEmail.objects.filter(...).exists():
        raise DuplicateEmailError  # ← This one IS caught!
```

**Evidence of Inconsistency** (line 154):
```python
except DuplicateEmailError:
    return self.respond({"detail": "Email already associated"}, status=409)
# InvalidEmailError NOT in except clause → 500!
```

### Bug 2: KeyError in OAuth Configuration

**Severity**: Medium
**File**: `src/sentry/identity/oauth2.py:103`
**Endpoint**: `GET /extensions/github/setup/`

**The Bug**:
```python
def _get_oauth_parameter(self, parameter_name):
    # ... check class property, config, provider_model ...
    raise KeyError(f'Unable to resolve OAuth parameter "{parameter_name}"')
```

**Impact**: Self-hosted Sentry users see 500 when clicking "Connect GitHub" if not configured.

---

## Airflow

### Bug 1: TypeError in Asset Expression Parsing

**Severity**: Medium
**File**: `api_fastapi/core_api/services/ui/structure.py:69`
**Endpoint**: `GET /structure_data`

**The Bug**:
```python
if nested_expr_key in ("any", "all"):
    nested_expression = expr
elif nested_expr_key in ("asset", "alias", "asset-name-ref", "asset-uri-ref"):
    asset_info = expr[nested_expr_key]
else:
    raise TypeError(f"Unsupported type: {expr.keys()}")
```

**Impact**: DAG with unexpected asset expression key returns 500.

### Bug 2: RuntimeError from Uninitialized Auth Manager

**Severity**: High
**File**: `api_fastapi/app.py:158-165`
**Endpoints**: Multiple (6+ routes including `/auth/menus`)

**The Bug**:
```python
def get_auth_manager() -> BaseAuthManager:
    if _AuthManagerState.instance is None:
        raise RuntimeError(
            "Auth Manager has not been initialized yet. "
            "The `init_auth_manager` method needs to be called first."
        )
    return _AuthManagerState.instance
```

**Impact**: If auth manager initialization fails, multiple routes return 500.

### Bug 3: ValueError in Task Instance Run

**Severity**: Medium
**File**: `api_fastapi/execution_api/routes/task_instances.py:224-226`
**Endpoint**: `PATCH /{task_instance_id}/run`

**The Bug**:
```python
if not dr:
    log.error("DagRun not found", dag_id=ti.dag_id, run_id=ti.run_id)
    raise ValueError(f"DagRun with dag_id={ti.dag_id} and run_id={ti.run_id} not found.")
```

**Evidence of Inconsistency**: Route catches `SQLAlchemyError` but not `ValueError`.

### Bugs 4-5: Additional ValueError instances

Similar patterns in `calendar.py:292,301` where ValueError escapes without handling.

---

## Superset (Good Practices - No Real Bugs)

Superset demonstrates excellent exception handling:

1. **Global Flask error handlers** catch all exceptions
2. **Well-designed exception hierarchy** with HTTP status codes baked in
3. All flagged issues were false positives due to comprehensive catch-all handlers

---

## Label Studio

### Bug 1: DataManagerException Inherits from Exception

**Severity**: Medium
**File**: `data_manager/functions.py:21-22`
**Endpoints**: Multiple Data Manager API endpoints

**The Bug**:
```python
class DataManagerException(Exception):  # Should extend APIException!
    pass
```

Raised in 5 places, all become 500 errors.

**Evidence of Inconsistency**: Label Studio HAS a proper base class:
```python
class LabelStudioAPIException(APIException):
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
```

And other exceptions use it correctly:
```python
class AnnotationDuplicateError(LabelStudioAPIException):
    status_code = status.HTTP_409_CONFLICT
```

### Bug 2 & 3: Storage Sync Endpoints Missing Exception Handling

**Severity**: High
**File**: `io_storages/api.py:129-138` and `:153-162`
**Endpoints**: 10 endpoints across all storage providers (S3, Azure, GCS, Redis, LocalFiles)

**The Bug**:
```python
def post(self, request, *args, **kwargs):
    storage = self.get_object()
    storage.validate_connection()  # <-- KeyError can escape!
    storage.sync()
```

**Evidence of Inconsistency**: Same `validate_connection()` IS wrapped elsewhere:
```python
# io_storages/api.py:86-97
def perform_create(self, serializer):
    try:
        instance.validate_connection()
    except Exception as exc:
        raise ValidationError(exc)  # <-- Properly wrapped!
```

**Side-by-side**:
| Operation | Exception Handling | Response |
|-----------|-------------------|----------|
| Create storage | try/except → ValidationError | 400 |
| Validate storage | try/except → ValidationError | 400 |
| **Sync storage** | **NONE** | **500** |

---

## Redash

### Bug 1: QueryDetachedFromDataSourceError Not Caught

**Severity**: High
**File**: `handlers/query_results.py:204-214`
**Endpoint**: `GET /api/queries/{id}/dropdowns/{id}`

**The Bug**:
```python
class QueryDropdownsResource(BaseResource):
    def get(self, query_id, dropdown_query_id):
        # ...
        return dropdown_values(dropdown_query_id, self.current_org)  # No try/except!
```

**Evidence of Inconsistency**: Same call wrapped 10 lines earlier:
```python
class QueryResultDropdownResource(BaseResource):
    def get(self, query_id):
        try:
            return dropdown_values(query_id, self.current_org)
        except QueryDetachedFromDataSourceError as e:
            abort(400, message=str(e))  # <-- Properly handled!
```

### Bug 2: KeyError on Invalid Settings

**Severity**: Medium
**File**: `handlers/settings.py:49`
**Endpoint**: `POST /api/settings/organization`

**The Bug**: User input passed directly to `set_setting()` which raises KeyError for invalid keys.

**Evidence of Inconsistency**: Other handlers validate input with `require_fields()` + `abort(400)`.

### Bug 3: ValueError on Invalid Boolean Params

**Severity**: Low
**File**: `handlers/users.py:120,124`
**Endpoint**: `GET /api/users?disabled=invalid`

**The Bug**:
```python
disabled = request.args.get("disabled", "false")
disabled = parse_boolean(disabled)  # Raises ValueError on invalid!
```

**Evidence of Inconsistency**: Same file uses `abort(400, message="...")` for page validation.

---

## Datasette (Well-Written - No Real Bugs)

Datasette has comprehensive exception handling throughout. Our analysis found no real bugs - the codebase demonstrates good practices with proper try/except blocks around operations that can fail.

---

## Analysis Commands Used

```bash
# Clone and analyze each project
bubble flask audit -d /path/to/project      # Flask/Flask-RESTful
bubble django audit -d /path/to/project     # Django/DRF
bubble fastapi audit -d /path/to/project    # FastAPI

# Investigate specific exceptions
bubble raises ExceptionType -d /path/to/project
bubble catches ExceptionType -d /path/to/project
bubble escapes function_name -d /path/to/project
```
