# Custom Airflow Integration Design

## Overview

Airflow has migrated from Flask to **FastAPI** for its web API. A custom integration would need to:

1. Detect FastAPI route handlers
2. Understand Airflow's exception hierarchy
3. Recognize Airflow's global error handlers

## Real Bug Found

**Endpoint**: `GET /ui/structure/structure_data`

**Call path**:
```
routes/ui/structure.py:52 structure_data()
  → services/ui/structure.py:37 get_upstream_assets()
    → Line 69: raise TypeError(f"Unsupported type: {expr.keys()}")
    → Line 102: raise TypeError(f"Unsupported type: {asset_type}")
```

**Issue**: No try/except around `get_upstream_assets()` call in the route handler.

**File**: `/tmp/airflow/airflow-core/src/airflow/api_fastapi/core_api/routes/ui/structure.py`
- Lines 151-154 call `get_upstream_assets()` without catching `TypeError`

**GitHub**: https://github.com/apache/airflow/blob/main/airflow-core/src/airflow/api_fastapi/core_api/routes/ui/structure.py

## Airflow Architecture

### Directory Structure
```
airflow-core/src/airflow/
├── api_fastapi/                    # FastAPI web API
│   ├── core_api/
│   │   ├── routes/public/          # Public REST endpoints
│   │   ├── routes/ui/              # UI-specific endpoints
│   │   └── services/               # Business logic
│   ├── common/exceptions.py        # Global error handlers
│   └── execution_api/              # Task execution API
├── exceptions.py                   # Core exception classes
└── models/                         # Data models
```

### Exception Hierarchy

```python
# airflow/exceptions.py
class AirflowException(Exception):
    status_code = 500  # Default

class AirflowBadRequest(AirflowException):
    status_code = 400

class AirflowNotFoundException(AirflowException):
    status_code = 404
```

### Global Error Handlers

Only two handlers registered in `api_fastapi/common/exceptions.py`:

```python
ERROR_HANDLERS = [
    _UniqueConstraintErrorHandler(),  # IntegrityError → 409
    DagErrorHandler(),                 # DeserializationError → 500
]
```

**Gap**: No handler for `ValueError`, `TypeError`, `KeyError` - they become generic 500s.

## Integration Implementation

### 1. FastAPI Route Detector

```python
# flow/integrations/airflow/detector.py
import libcst as cst

class FastAPIRouteVisitor(cst.CSTVisitor):
    """Detect FastAPI route decorators: @router.get, @router.post, etc."""

    def visit_FunctionDef(self, node: cst.FunctionDef) -> None:
        for decorator in node.decorators:
            if self._is_fastapi_route(decorator):
                # Extract route info: path, method, function name
                pass

    def _is_fastapi_route(self, decorator: cst.Decorator) -> bool:
        # Match patterns like:
        # @router.get("/path")
        # @structure_router.get("/structure_data")
        pass
```

### 2. Airflow Exception Semantics

```python
# flow/integrations/airflow/semantics.py
EXCEPTION_RESPONSES = {
    "AirflowBadRequest": "400 Bad Request",
    "AirflowNotFoundException": "404 Not Found",
    "AirflowClusterPolicyViolation": "400 Bad Request",
    # etc.
}

HANDLED_BASE_CLASSES = [
    "airflow.exceptions.AirflowException",
]
```

### 3. Integration Class

```python
# flow/integrations/airflow/__init__.py
from flow.integrations.base import Integration

class AirflowIntegration(Integration):
    name = "airflow"

    def get_exception_response(self, exc_type: str) -> str | None:
        return EXCEPTION_RESPONSES.get(exc_type)

    def get_handled_base_classes(self) -> list[str]:
        return HANDLED_BASE_CLASSES
```

### 4. CLI Commands

```bash
# Audit FastAPI endpoints
bubble airflow audit -d /path/to/airflow

# List endpoints
bubble airflow entrypoints -d /path/to/airflow

# Trace routes to exception
bubble airflow routes-to TypeError -d /path/to/airflow
```

## Configuration

`.flow/config.yaml` for Airflow projects:

```yaml
handled_base_classes:
  - airflow.exceptions.AirflowException
  - fastapi.HTTPException

async_boundaries:
  - "*.apply_async"  # Celery tasks
  - "*.delay"
```

## Key Differences from Flask/Django

| Aspect | Flask | FastAPI/Airflow |
|--------|-------|-----------------|
| Route decorator | `@app.route` | `@router.get` |
| Error handlers | `@app.errorhandler` | `app.add_exception_handler` |
| Validation | Manual | Pydantic (automatic 422) |
| Path params | `<param>` | `{param}` |

## Limitations

1. **Task execution code** is NOT web API - operators run in workers
2. **Provider code** (Google, AWS, etc.) is task-level, not web-level
3. **Celery tasks** (.apply_async, .delay) create async boundaries

## Summary

A custom Airflow integration would enable detection of real bugs like the `TypeError` in `get_upstream_assets()`. The implementation requires:

1. FastAPI-specific route detection
2. Understanding Airflow's exception hierarchy
3. Configuration for Airflow-specific patterns

Estimated effort: ~200 lines of code, modeled on existing Flask/Django integrations.
