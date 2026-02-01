# Detailed Bug Analysis: Apache Superset Exception Handling Issues

## Audit Summary

- **Codebase**: Apache Superset (1,129 Python files)
- **Total time**: ~27 seconds
- **Flask entrypoints found**: 251
- **With issues**: 133 (53%)
- **Clean**: 85 (34%)
- **Partially covered**: 33 (13%)

## Bug #1: ValueError in Expression Validation API

### Location
`superset/datasource/api.py:276,286`

### Call Path
```
POST /datasource/<type>/<id>/validate_expression/
  → DatasourceValidateExpressionApi.post()
    → _get_datasource()
      → raise ValueError(f"Invalid datasource type: {datasource_type}")
    → _parse_validation_request()
      → raise ValueError("Expression is required")
```

### Code
```python
def _get_datasource(self, datasource_type, datasource_id):
    try:
        datasource = DatasourceDAO.get_datasource(...)
    except ValueError:
        raise ValueError(f"Invalid datasource type: {datasource_type}") from None
        # ↑ Only caught by generic handler!

def _parse_validation_request(self):
    if not expression:
        raise ValueError("Expression is required")  # ← Only caught by generic handler!
```

### What SHOULD Happen
- User should see: **"Invalid datasource type 'foo'. Valid types are: table, query"**
- HTTP status: **400 Bad Request**

### What ACTUALLY Happens
- User sees: **"Internal Server Error"** or generic error
- HTTP status: **500**

---

## Bug #2: Generic Exception in Encryption Module

### Location
`superset/utils/encrypt.py:59,83`

### Code
```python
def create(...):
    if app_config:
        return EncryptedType(...)

    raise Exception("Missing app_config kwarg")  # ← Generic Exception!

def create(...):
    if self._concrete_type_adapter:
        return adapter

    raise Exception("App not initialized yet. Please call init_app first")  # ← Generic!
```

### What SHOULD Happen
Configuration errors during startup should:
- Log clear error message
- Fail fast with specific exception type
- Guide admin to fix configuration

### What ACTUALLY Happens
- Generic `Exception` propagates through call stack
- If reached during request, user sees 500
- No guidance on what's misconfigured

---

## Bug #3: QueryNotFoundException Not Handled

### Location
`superset/daos/query.py:63`

### Call Path
```
POST /api/v1/query/stop
  → QueryRestApi.stop()
    → QueryDAO.stop_query()
      → raise QueryNotFoundException(f"Query with client_id {client_id} not found")
```

### Code
```python
@staticmethod
def stop_query(client_id: str) -> None:
    query = db.session.query(Query).filter_by(client_id=client_id).one_or_none()
    if not query:
        raise QueryNotFoundException(f"Query with client_id {client_id} not found")
        # ↑ Only caught by generic handler
```

### What SHOULD Happen
- User should see: **"Query not found"**
- HTTP status: **404 Not Found**

### What ACTUALLY Happens
- Only caught by generic `except Exception` handler
- May return 500 or generic error

---

## Bug #4: CacheLoadError on Dashboard Load

### Location
`superset/viz.py:566`, `superset/common/utils/query_cache_manager.py:210`

### Call Path
```
GET /api/v1/dashboard/<id>
  → Load dashboard data
    → Query cache
      → raise CacheLoadError("Cache data corrupted")
```

### Impact
When cache is corrupted or incompatible after upgrade:
- Dashboard fails to load entirely
- User sees 500 instead of "refreshing data..."

---

## Bug #5: DBAPIError from Database Connections

### Location
`superset/commands/database/test_connection.py:169`

### Code
```python
if not alive:
    raise DBAPIError(ex_str or None, None, None)  # ← Raw SQLAlchemy error!
```

### What SHOULD Happen
- User should see: **"Could not connect to database. Check your connection settings."**
- Show specific connection error (timeout, auth failed, etc.)

### What ACTUALLY Happens
- Raw `DBAPIError` may expose internal database details
- User sees cryptic error message

---

## Bug #6: SqlLabException in SQL Editor

### Location
`superset/commands/sql_lab/execute.py:125,197`

### Call Path
```
POST /api/v1/sqllab/execute/
  → ExecuteSqlCommand.run()
    → except Exception as ex:
        raise SqlLabException(self._execution_context, exception=ex)
```

### Code
```python
try:
    # ... execute query
except (SupersetErrorException, SupersetErrorsException):
    raise
except Exception as ex:
    raise SqlLabException(self._execution_context, exception=ex) from ex
    # ↑ Only caught by generic handler!
```

### Impact
Any unexpected error in SQL execution becomes `SqlLabException` which is only caught by generic handler.

---

## Statistics by Exception Type

| Exception | Count | Impact |
|-----------|-------|--------|
| ValueError | 34+ | Validation → 500 |
| SupersetException | 15+ | Generic errors |
| QueryObjectValidationError | 65+ | Query building failures |
| NotImplementedError | 44+ | Abstract methods hit |
| CacheLoadError | 2+ | Cache failures |
| Exception (generic) | 25+ | Various |

---

## High-Risk Endpoints

| Endpoint | Issues | Risk |
|----------|--------|------|
| `DELETE /` (datasets) | 30+ exceptions | Data operations fail with 500 |
| `POST /validate_expression/` | ValueError not handled | Validation → 500 |
| `POST /stop` | QueryNotFoundException | Stop query → 500 |
| `GET /export/` | 20+ exceptions | Export fails mysteriously |

---

## Recommendations

1. **Create SupersetHTTPException base class**
   ```python
   class SupersetHTTPException(SupersetException):
       status_code: int = 500

   class SupersetBadRequest(SupersetHTTPException):
       status_code = 400

   class SupersetNotFound(SupersetHTTPException):
       status_code = 404
   ```

2. **Add exception handler that converts known exceptions**
   ```python
   @app.errorhandler(QueryNotFoundException)
   def handle_query_not_found(e):
       return {"error": str(e)}, 404
   ```

3. **Replace generic ValueError with domain exceptions**
   ```python
   # Instead of:
   raise ValueError("Invalid datasource type")

   # Use:
   raise InvalidDatasourceTypeError(datasource_type, valid_types)
   ```

4. **Never use bare `Exception`**
   - Replace `raise Exception("message")` with specific types

---

## Detection Performance

| Metric | Value |
|--------|-------|
| Files analyzed | 1,129 |
| Functions | ~8,000 |
| Call sites | ~40,000 |
| Total time | **27 seconds** |
| Entrypoints analyzed | 251 |
| Issues found | 133 endpoints (53%) |
