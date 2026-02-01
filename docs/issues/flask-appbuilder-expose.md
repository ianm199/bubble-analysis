# Flask-AppBuilder @expose Decorator Support

## Issue

Flow does not detect HTTP routes defined using Flask-AppBuilder's `@expose()` decorator. This causes Flow to miss routes in major projects including:

- **Apache Airflow** - FAB provider views (`providers/fab/src/airflow/providers/fab/www/views.py`)
- **Apache Superset** - All API endpoints (`superset/databases/api.py`, etc.)

## Impact

In Superset dogfooding, Flow detected only **4 routes** out of **100+ actual routes** because the vast majority use `@expose()`.

## Pattern

Flask-AppBuilder extends Flask with a class-based view pattern:

```python
from flask_appbuilder import IndexView, expose

class DatabaseRestApi(BaseSupersetModelRestApi):

    @expose("/<int:pk>/connection", methods=("GET",))
    @protect()
    @safe
    def get_connection(self, pk: int) -> Response:
        """Get database connection info."""
        database = DatabaseDAO.find_by_id(pk)
        # ... handler code
```

Compare to standard Flask (which Flow already detects):

```python
@app.route("/connection/<int:pk>", methods=["GET"])
def get_connection(pk: int):
    # ... handler code
```

## Detection Requirements

To support `@expose`, Flow needs to:

1. **Detect the decorator**: Match `@expose(...)` pattern in AST
2. **Extract route info**: Parse the path and methods from decorator arguments
3. **Handle class context**: Routes are methods on classes that inherit from FAB base classes
4. **Resolve class registration**: FAB classes are registered via `appbuilder.add_view()` or `appbuilder.add_api()`

## Examples Found in Dogfooding

### Airflow

```python
# providers/fab/src/airflow/providers/fab/www/views.py
from flask_appbuilder import IndexView, expose

class FabIndexView(IndexView):
    @expose("/")
    def index(self):
        return redirect(conf.get("api", "base_url", fallback="/"), code=302)
```

### Superset

```python
# superset/databases/api.py
class DatabaseRestApi(BaseSupersetModelRestApi):

    @expose("/<int:pk>", methods=("GET",))
    @protect()
    @safe
    def get(self, pk: int, **kwargs: Any) -> Response:
        """Get a database."""
        # ...

    @expose("/test_connection/", methods=("POST",))
    @protect()
    @statsd_metrics
    @event_logger.log_this_with_context(...)
    def test_connection(self) -> FlaskResponse:
        """Test a database connection."""
        # ...
```

## Implementation Approach

### Option 1: Simple Pattern Match

Add an `@expose` visitor similar to Flask's `@app.route`:

```python
class FlaskAppBuilderRouteVisitor(cst.CSTVisitor):
    def visit_Decorator(self, node):
        if self._is_expose_decorator(node):
            path, methods = self._extract_route_info(node)
            self.routes.append(Entrypoint(...))
```

Pros: Simple, catches most cases
Cons: Doesn't know the URL prefix from class registration

### Option 2: Full FAB Support

Track class inheritance and `add_view()`/`add_api()` calls to resolve full URL paths.

Pros: More accurate paths
Cons: Complex, may not be worth the effort

## Recommendation

Start with Option 1 (simple pattern match). Even without full URL resolution, detecting that a method is an HTTP handler enables exception flow analysis.

## Priority

**High** - Two of the three Tier 1 dogfooding targets (Airflow, Superset) use Flask-AppBuilder extensively. Without this support, Flow misses the majority of their routes.

## Related

- Dogfooding results: Airflow (`/tmp/dogfood-results/airflow.json`)
- Dogfooding results: Superset (`/tmp/dogfood-results/superset.json`)
