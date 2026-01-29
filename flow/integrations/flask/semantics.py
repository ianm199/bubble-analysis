"""Flask exception-to-HTTP-response mappings.

Defines which exceptions Flask converts to HTTP responses automatically.
"""

EXCEPTION_RESPONSES: dict[str, str] = {
    "werkzeug.exceptions.HTTPException": "HTTP {code}",
    "HTTPException": "HTTP {code}",
    "werkzeug.exceptions.NotFound": "HTTP 404",
    "NotFound": "HTTP 404",
    "werkzeug.exceptions.BadRequest": "HTTP 400",
    "BadRequest": "HTTP 400",
    "werkzeug.exceptions.Unauthorized": "HTTP 401",
    "Unauthorized": "HTTP 401",
    "werkzeug.exceptions.Forbidden": "HTTP 403",
    "Forbidden": "HTTP 403",
    "werkzeug.exceptions.InternalServerError": "HTTP 500",
    "InternalServerError": "HTTP 500",
}
