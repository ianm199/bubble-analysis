# Detailed Bug Analysis: Sentry Exception Handling Issues

## Bug #1: OAuth Configuration KeyError

### Location
`src/sentry/identity/oauth2.py:103`

### Call Path
```
User clicks "Connect Integration" (e.g., GitHub, GitLab)
  → GET /extensions/github/setup/
    → OAuth2Provider.get_pipeline_views()
      → get_oauth_client_id()
        → _get_oauth_parameter("client_id")
          → raise KeyError("Unable to resolve OAuth parameter 'client_id'")
```

### Code
```python
def _get_oauth_parameter(self, parameter_name):
    # Check class property
    try:
        prop = getattr(self, f"oauth_{parameter_name}")
        if prop != "":
            return prop
    except AttributeError:
        pass

    # Check pipeline config
    if self.config.get(parameter_name):
        return self.config.get(parameter_name)

    # Check provider model config
    model = self.pipeline.provider_model
    if model and model.config.get(parameter_name) is not None:
        return model.config.get(parameter_name)

    raise KeyError(f'Unable to resolve OAuth parameter "{parameter_name}"')  # ← ESCAPES
```

### What SHOULD Happen
When an OAuth integration is misconfigured (missing client_id, client_secret, or authorize_url):
- User should see: **"This integration is not properly configured. Please contact your administrator."**
- HTTP status: **503 Service Unavailable** or **400 Bad Request**
- Sentry should log the misconfiguration for admins

### What ACTUALLY Happens
- User sees: **"Internal Server Error"** or **"Something went wrong"**
- HTTP status: **500 Internal Server Error**
- Stack trace logged but no actionable message for user
- User has no idea what went wrong or what to do

### Impact
- **User Experience**: Confusing error when trying to connect integrations
- **Debugging**: Admins need to check logs to understand the issue
- **Security**: Stack traces in logs may expose internal paths

### Fix
```python
def _get_oauth_parameter(self, parameter_name):
    # ... existing lookup logic ...

    # Instead of KeyError, raise a handled exception
    raise IntegrationConfigurationError(
        f"OAuth integration missing required parameter: {parameter_name}"
    )
```

---

## Bug #2: InvalidEmailError Not Caught

### Location
`src/sentry/users/api/endpoints/user_emails.py:45,70`

### Call Path
```
User submits POST /api/0/users/{user_id}/emails/
  → UserEmailsEndpoint.post()
    → add_email() or add_email_signed()
      → if email is None: raise InvalidEmailError  # ← NOT CAUGHT
```

### Code
```python
def add_email(email: str, user: User) -> UserEmail:
    if email is None:
        raise InvalidEmailError  # ← This escapes!

    if UserEmail.objects.filter(...).exists():
        raise DuplicateEmailError  # ← This IS caught

# In the endpoint:
try:
    new_useremail = add_email(email, user)
except DuplicateEmailError:  # ← Only catches DuplicateEmailError!
    return self.respond({"detail": "..."}, status=409)
# InvalidEmailError escapes → 500
```

### What SHOULD Happen
When email validation fails:
- User should see: **"Invalid email address provided"**
- HTTP status: **400 Bad Request**

### What ACTUALLY Happens
- User sees: **"Internal Server Error"**
- HTTP status: **500 Internal Server Error**

### Likelihood
**Low** - The DRF serializer validates email format first. This would only trigger if:
1. Serializer has a bug that passes None through
2. Someone bypasses the serializer

### Fix
```python
try:
    new_useremail = add_email(email, user)
except DuplicateEmailError:
    return self.respond({"detail": "Email already associated"}, status=409)
except InvalidEmailError:
    return self.respond({"detail": "Invalid email address"}, status=400)
```

---

## Bug #3: RuntimeError in Event Manager

### Location
`src/sentry/event_manager.py:398,403`

### Call Path
```
SDK sends event to /api/{project_id}/store/
  → EventManager.normalize()
    → _normalize_impl()
      → raise RuntimeError("Initialized with one project, called save with another")
```

### Code
```python
def _normalize_impl(self, project_id: int | None = None) -> None:
    if self._project and project_id and project_id != self._project.id:
        raise RuntimeError(
            "Initialized EventManager with one project ID and called save() with another one"
        )

    if self._normalized:
        raise RuntimeError("Already normalized")
```

### What SHOULD Happen
This is an **internal invariant check** - it detects bugs in Sentry's own code.
- Should not happen in production if code is correct
- If it does happen, should alert Sentry developers, not users

### What ACTUALLY Happens
- SDK gets: **500 Internal Server Error**
- Event is lost
- SDK may retry, causing duplicate events or retry storms

### Impact
- **Data Loss**: Events not stored
- **SDK Behavior**: Retries may cause load spikes
- **Debugging**: Hard to understand why events disappear

### Fix
This is a defensive assertion. Options:
1. Log error + return graceful failure to SDK
2. Keep RuntimeError but ensure it's caught at API boundary
3. Use `assert` in debug mode, silent handling in production

---

## Summary Table

| Bug | Exception | Caught? | User Sees | Should See |
|-----|-----------|---------|-----------|------------|
| OAuth config | `KeyError` | No | 500 | "Integration not configured" |
| Email validation | `InvalidEmailError` | No | 500 | "Invalid email" (400) |
| Event normalize | `RuntimeError` | No | 500 | Graceful error to SDK |

## Detection Method

These bugs were found by Flow's exception propagation analysis:
1. Build call graph of 7,469 Python files
2. Identify raise sites and catch sites
3. Propagate exceptions through call graph
4. Flag exceptions that reach API endpoints without handlers

Total analysis time: **1 minute 27 seconds** (after optimizations)
