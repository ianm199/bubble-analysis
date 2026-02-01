# Detailed Bug Analysis: Apache Airflow Exception Handling Issues

## Audit Summary

- **Codebase**: Apache Airflow (~50k Python files)
- **Extraction time**: 70s
- **Propagation time**: 11s
- **Flask entrypoints found**: 4
- **With issues**: 2
- **Clean**: 2

## Bug #1: CalledProcessError Escaping from Go Module Utils

### Location
`providers/google/src/airflow/providers/google/go_module_utils.py:56`

### Call Path
```
GET /show/<pk> (User Management View)
  → Some Google Cloud operator execution
    → go_module_utils.init_module() or install_dependencies()
      → _execute_in_subprocess()
        → raise subprocess.CalledProcessError(exit_code, cmd)  ← ESCAPES
```

### Code
```python
def _execute_in_subprocess(cmd, cwd):
    proc = subprocess.Popen(cmd, ...)
    exit_code = proc.wait()
    if exit_code != 0:
        raise subprocess.CalledProcessError(exit_code, cmd)  # ← Escapes!
```

### What SHOULD Happen
When a Go subprocess fails:
- User should see: **"Failed to initialize Go module: <specific error>"**
- HTTP status: **500** with structured error
- Log detailed subprocess output for debugging

### What ACTUALLY Happens
- User sees: **"Internal Server Error"** with no context
- Stack trace in logs but user has no idea what went wrong

### Impact
- **User Experience**: Confusing error when Google Cloud operators fail
- **Debugging**: Hard to understand subprocess failures

---

## Bug #2: AirflowNotFoundException Not Properly Handled

### Location
`task-sdk/src/airflow/sdk/definitions/connection.py:216`

### Call Path
```
GET /repair_databricks_job/<dag_id>/<run_id>
  → DatabricksHook() initialization
    → Connection.get(conn_id)
      → _handle_connection_error()
        → raise AirflowNotFoundException(f"The conn_id `{conn_id}` isn't defined")
```

### Code
```python
@classmethod
def _handle_connection_error(cls, e: AirflowRuntimeError, conn_id: str) -> None:
    if e.error.error == ErrorType.CONNECTION_NOT_FOUND:
        raise AirflowNotFoundException(f"The conn_id `{conn_id}` isn't defined")  # ← Only caught by generic handler
    raise
```

### What SHOULD Happen
When a Databricks connection isn't configured:
- User should see: **"Connection 'databricks_default' not found. Please configure it in Airflow connections."**
- HTTP status: **404 Not Found** or **400 Bad Request**
- Link to connection configuration page

### What ACTUALLY Happens
- User sees: **"Internal Server Error"** or generic error
- Only caught by generic `except Exception` handler
- No guidance on how to fix

---

## Bug #3: RuntimeError (130+ occurrences)

### Locations
- `task-sdk/src/airflow/sdk/execution_time/task_mapping.py:86`
- `task-sdk/src/airflow/sdk/definitions/param.py:336`
- And 130+ more

### Sample Code
```python
# From param.py
def resolve(self, value, ...):
    if self.schema is None:
        raise RuntimeError("Cannot resolve param without schema")
```

### Impact
Generic `RuntimeError` with various messages escaping through call chains. These are often:
- Configuration errors
- Internal invariant violations
- Missing required setup

All become generic 500 errors to users.

---

## Bug #4: ValueError (509+ occurrences)

### Locations
- `airflow-ctl/src/airflowctl/ctl/console_formatting.py:118,125`
- And 509+ more throughout codebase

### Pattern
```python
# Common pattern
if not valid_input:
    raise ValueError(f"Invalid value: {value}")
```

### Impact
Validation errors that could give users helpful feedback instead become 500s.

---

## Bug #5: HTTPError from Provider Hooks

### Location
`providers/google/src/airflow/providers/google/cloud/hooks/datafusion.py:180,185`

### Call Path
```
GET /show/<pk>
  → DataFusion operator execution
    → datafusion.py hook
      → requests.get(...)
        → response.raise_for_status()
          → raise HTTPError  ← ESCAPES
```

### What SHOULD Happen
When an external API call fails:
- User should see: **"Failed to connect to Google Cloud DataFusion: 403 Forbidden"**
- Include troubleshooting steps (check IAM permissions, etc.)

### What ACTUALLY Happens
- Raw `HTTPError` escapes to user as 500

---

## False Positives Identified

### SystemExit in CLI Commands
```
SystemExit (airflow-ctl/src/airflowctl/ctl/commands/connection_command.py:41)
```
This is from CLI commands, not web endpoints. The call graph analysis connected them due to shared utility code, but they're separate execution contexts.

---

## Summary Statistics

| Exception Type | Count | Real Bug? |
|----------------|-------|-----------|
| AirflowException | 1,152+ | Varies - some handled |
| RuntimeError | 130+ | Yes - should be specific errors |
| ValueError | 509+ | Yes - validation errors |
| HTTPError | 2+ | Yes - API failures |
| CalledProcessError | 2+ | Yes - subprocess failures |
| AirflowNotFoundException | 15+ | Yes - should be 404 |
| SystemExit | 23+ | No - CLI only |

## Recommendations

1. **Create Airflow-specific HTTP exception classes**
   ```python
   class AirflowHTTPException(AirflowException):
       status_code: int
       user_message: str
   ```

2. **Add exception handler middleware** that converts known exceptions to proper HTTP responses

3. **Replace generic RuntimeError/ValueError** with domain-specific exceptions

4. **Wrap external API calls** (Google Cloud, Databricks, etc.) with proper error handling

## Detection Performance

| Metric | Value |
|--------|-------|
| Files analyzed | ~50,000 |
| Extraction time | 70s |
| Propagation time | 11s |
| Total time | **~82s** |
| Flask entrypoints | 4 |
| Issues found | 2 entrypoints with unhandled exceptions |
