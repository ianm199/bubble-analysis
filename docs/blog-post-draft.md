# Finding Bugs in Large Open Source Python APIs with Bespoke Static Analysis

*How we built a tool that found real exception handling bugs in Sentry, Airflow, and Superset in under 2 minutes each*

---

## The Problem: APIs Should Never 500

Every Python web developer has seen it: a user triggers some edge case, an exception bubbles up unhandled, and your API returns a generic "Internal Server Error" with a 500 status code.

The user has no idea what went wrong. Your logs have a stack trace, but by the time you investigate, the context is lost. And somewhere, a customer is frustrated.

**The goal is simple: APIs should return meaningful errors, not crash.**

But in large codebases, ensuring every exception is properly handled is nearly impossible to verify manually. You can't grep for "what exceptions can reach this endpoint" - it requires understanding the entire call graph.

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

We ran the tool on three major open source projects:

| Project | Files | Analysis Time | Endpoints | With Issues |
|---------|-------|---------------|-----------|-------------|
| **Sentry** | 7,469 | 1m 27s | 61 | 52 (85%) |
| **Airflow** | 50,000 | 1m 22s | 4 | 2 (50%) |
| **Superset** | 1,129 | 27s | 251 | 133 (53%) |

### Sentry: OAuth KeyError

```python
# sentry/identity/oauth2.py:103
def _get_oauth_parameter(self, parameter_name):
    if self.config.get(parameter_name):
        return self.config.get(parameter_name)
    # ... more lookups ...
    raise KeyError(f'Unable to resolve OAuth parameter "{parameter_name}"')
```

**What happens**: User clicks "Connect GitHub" with a misconfigured integration.
**What they see**: "Internal Server Error"
**What they should see**: "This integration is not properly configured. Contact your administrator."

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

The tool is open source: [link to repo]

```bash
pip install flow-analysis
flow flask audit -d /path/to/your/project
```

It will show you which endpoints have unhandled exceptions and where they come from.

---

## Conclusion

Static analysis for exception flow is surprisingly tractable in Python. Despite the dynamic nature of the language, we can build useful call graphs and find real bugs.

The three projects we analyzed are well-maintained by experienced teams. Yet each had exception handling gaps that would cause mysterious 500 errors for users. This isn't a criticism - it's a testament to how hard this problem is to solve manually.

Tools like this make it possible to systematically verify exception handling across an entire codebase, turning "I hope we handle all the errors" into "I know we handle all the errors."

---

*Built with libcst, ProcessPoolExecutor, and a lot of fixpoint iteration.*
