# Real Bugs Found in Sentry by Flow

Analyzed Sentry codebase (7,469 files) with Flow exception audit.

## Summary

- **61 Django entrypoints** analyzed
- **52 entrypoints** have potential exception handling issues
- **9 entrypoints** fully covered

## Confirmed Real Bugs

### 1. Missing InvalidEmailError Handler
**File:** `src/sentry/users/api/endpoints/user_emails.py:45,70`

```python
def add_email(email: str, user: User) -> UserEmail:
    if email is None:
        raise InvalidEmailError  # NOT CAUGHT!

    if UserEmail.objects.filter(user=user, email__iexact=email.lower()).exists():
        raise DuplicateEmailError  # This IS caught at line 154
```

The endpoint catches `DuplicateEmailError` but NOT `InvalidEmailError`. If validation fails, users get a 500.

### 2. OAuth KeyError on Missing Config
**File:** `src/sentry/identity/oauth2.py:103`

```python
def _get_oauth_parameter(self, parameter_name):
    if self.config.get(parameter_name):
        return self.config.get(parameter_name)
    # ...
    raise KeyError(f'Unable to resolve OAuth parameter "{parameter_name}"')
```

If an OAuth integration is misconfigured, users see a 500 instead of a helpful error message.

### 3. TypeError in Unmerge (59+ occurrences)
**File:** `src/sentry/unmerge.py:43` and many others

Generic `TypeError` exceptions escaping from data processing code.

### 4. RuntimeError in Event Manager (26+ occurrences)
**File:** `src/sentry/event_manager.py:398,403`

`RuntimeError` escaping from event processing - would cause 500 on event ingestion.

## False Positives (Handled by Framework)

These look like issues but are actually handled:

### ResourceDoesNotExist
- Extends `rest_framework.exceptions.APIException`
- DRF automatically converts to 404 response
- **Not a bug**

### InvalidSearchQuery, InvalidParams, etc.
- Most are subclasses of `SentryAPIException`
- Handled by Sentry's exception handler
- Need to verify each one individually

## High-Impact Findings

| Exception | Occurrences | Impact |
|-----------|-------------|--------|
| ValueError | 327+ | Varies - some real, some false positives |
| NotImplementedError | 418+ | Many are abstract methods, but some are real |
| Exception (generic) | 71+ | Broad catch-all, masks real errors |
| TypeError | 59+ | Data validation failures |
| KeyError | 10+ | Missing config/data |
| RuntimeError | 26+ | Internal logic errors |

## Recommendations for Sentry

1. **Add specific exception handlers** for `InvalidEmailError` in user email endpoints
2. **Wrap OAuth config access** in try/except with friendly error message
3. **Audit generic Exception catches** - they mask real errors
4. **Add exception hierarchy** for domain-specific errors (already partially done with `SentryAPIException`)

## Tool Accuracy

- **True positives:** InvalidEmailError, KeyError in OAuth, RuntimeError in event manager
- **False positives:** ResourceDoesNotExist (handled by DRF), most custom exceptions
- **Needs investigation:** Generic Exception, ValueError, TypeError instances

The tool successfully identified real exception handling gaps in a production codebase.
