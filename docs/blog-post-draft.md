# Finding Bugs in Open Source Python APIs with Static Exception Flow Analysis

*We built a tool that found real bugs in httpbin, Sentry, Airflow, and Superset - including one you can trigger right now*

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

We ran the tool on four open source projects:

| Project | Files | Analysis Time | Endpoints | Real Issues* |
|---------|-------|---------------|-----------|--------------|
| **httpbin** | 8 | 0.8s | 55 | 1 |
| **Sentry** | 7,469 | 87s | 52 | 43 |
| **Airflow** | 50,000 | 82s | 4 | 2 |
| **Superset** | 1,129 | 27s | 251 | 133 |

*After filtering framework-handled exceptions (e.g., DRF's `APIException` subclasses)

### Case Study: Sentry

Sentry is a 7,469-file Python codebase with 52 Django REST Framework endpoints. Running the analysis:

```bash
git clone https://github.com/getsentry/sentry /tmp/sentry
flow django audit -d /tmp/sentry
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

#### Bug #1: Alert Rule Trigger Validation

**Call path**:
```
POST /api/0/organizations/{org}/alert-rules/
  → OrganizationAlertRuleIndexEndpoint.post()
    → AlertRuleSerializer.create()
      → create_alert_rule_trigger_action()
        → raise InvalidTriggerActionError("Must specify specific target type")
```

**Code**: [src/sentry/incidents/logic.py:1370](https://github.com/getsentry/sentry/blob/master/src/sentry/incidents/logic.py#L1370)
```python
def create_alert_rule_trigger_action(...):
    if target_type == AlertRuleTriggerAction.TargetType.SPECIFIC:
        if not target_identifier:
            raise InvalidTriggerActionError("Must specify specific target type")
```

**Reproduce**:
```bash
flow raises InvalidTriggerActionError -d /tmp/sentry
# Shows 18 raise sites, none caught at endpoint level
```

**What users see**: 500 Internal Server Error
**What they should see**: "Must specify a target for this notification type" (400)

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
flow raises KeyError -d /tmp/sentry | grep oauth2
# src/sentry/identity/oauth2.py:103  in _get_oauth_parameter()
```

**What users see**: 500 on self-hosted Sentry when clicking "Connect GitHub"
**What they should see**: "GitHub integration not configured. Check GITHUB_APP_ID in settings."

#### Bug #3: Email Validation

**Call path**:
```
POST /api/0/users/{user_id}/emails/
  → UserEmailsEndpoint.post()
    → add_email(email, user)
      → raise InvalidEmailError
```

**Code**: [src/sentry/users/api/endpoints/user_emails.py:45](https://github.com/getsentry/sentry/blob/master/src/sentry/users/api/endpoints/user_emails.py#L45)
```python
def add_email(email: str, user: User) -> UserEmail:
    if email is None:
        raise InvalidEmailError  # Not caught!
```

**What users see**: 500 when adding email to account
**What they should see**: "Invalid email address" (400)

### Superset: ValueError in Validation

```python
# superset/datasource/api.py:286
def _parse_validation_request(self):
    if not expression:
        raise ValueError("Expression is required")  # Only caught by generic handler!
```

**What happens**: User submits invalid data to the expression validator.
**What they see**: 500 error
**What they should see**: "Expression is required" with 400 status

### Airflow: CalledProcessError from Subprocesses

```python
# providers/google/go_module_utils.py:56
if exit_code != 0:
    raise subprocess.CalledProcessError(exit_code, cmd)  # Escapes to web!
```

**What happens**: A Go module build fails during a Google Cloud operator execution.
**What they see**: 500 error with no context
**What they should see**: "Failed to build Go module: <specific error>"

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
pip install flow-analysis

# Audit a Flask project
flow flask audit -d /path/to/your/project

# Audit a Django/DRF project
flow django audit -d /path/to/your/project

# Find where a specific exception is raised
flow raises ValueError -d /path/to/your/project

# Trace what can escape from a function
flow escapes my_function -d /path/to/your/project
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

The three projects we analyzed are well-maintained by experienced teams. Yet each had exception handling gaps that would cause mysterious 500 errors for users. This isn't a criticism - it's a testament to how hard this problem is to solve manually.

Tools like this make it possible to systematically verify exception handling across an entire codebase, turning "I hope we handle all the errors" into "I know we handle all the errors."

---

*Built with libcst, ProcessPoolExecutor, and a lot of fixpoint iteration.*
