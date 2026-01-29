"""FastAPI exception-to-HTTP-response mappings.

Defines which exceptions FastAPI converts to HTTP responses automatically.
"""

EXCEPTION_RESPONSES: dict[str, str] = {
    "fastapi.HTTPException": "HTTP {status_code}",
    "HTTPException": "HTTP {status_code}",
    "starlette.exceptions.HTTPException": "HTTP {status_code}",
    "pydantic.ValidationError": "HTTP 422",
    "pydantic_core.ValidationError": "HTTP 422",
    "ValidationError": "HTTP 422",
    "RequestValidationError": "HTTP 422",
}
