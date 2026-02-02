# Flask-RESTful Support Implementation Plan

## Problem Statement

The bubble tool cannot detect Flask-RESTful endpoints, which use call-based registration instead of decorator-based routes. This caused us to miss 60+ endpoints when auditing Redash (26k stars).

**Current detection**: `@app.route("/path")` decorators
**Flask-RESTful pattern**: `api.add_resource(ResourceClass, "/path")`

## Research Summary

From dogfooding against Redash, we identified these patterns:

### Pattern 1: Basic add_resource
```python
from flask_restful import Api, Resource

api = Api()

class UserResource(Resource):
    def get(self):    # GET /api/users/<id>
        pass
    def put(self):    # PUT /api/users/<id>
        pass
    def delete(self): # DELETE /api/users/<id>
        pass

api.add_resource(UserResource, "/api/users/<id>")
```

### Pattern 2: Custom API extensions (Redash-specific)
```python
class ApiExt(Api):
    def add_org_resource(self, resource, *urls, **kwargs):
        urls = [org_scoped_rule(url) for url in urls]
        return self.add_resource(resource, *urls, **kwargs)

api = ApiExt()
api.add_org_resource(UserListResource, "/api/users", endpoint="users")
```

### Pattern 3: Multiple URLs per Resource
```python
api.add_resource(QueryResultResource,
    "/api/query_results/<id>",
    "/api/queries/<query_id>/results")
```

## Implementation Plan

### Phase 1: Flask-RESTful Detector (flask/detector.py)

Add a new visitor class:

```python
class FlaskRESTfulVisitor(cst.CSTVisitor):
    """Detects Flask-RESTful Resource classes and add_resource() calls."""

    def __init__(self, file_path: str):
        self.file_path = file_path
        self.entrypoints: list[Entrypoint] = []
        self.resource_classes: dict[str, set[str]] = {}  # class_name -> {get, post, ...}
        self.resource_registrations: list[tuple[str, list[str]]] = []  # (class_name, [urls])

    def visit_ClassDef(self, node: cst.ClassDef) -> bool:
        # Detect classes with get/post/put/delete/patch methods
        # Store in self.resource_classes
        pass

    def visit_Call(self, node: cst.Call) -> bool:
        # Detect *.add_resource() or *.add_org_resource() calls
        # Extract (ResourceClass, urls) and store in self.resource_registrations
        pass

    def leave_Module(self, node: cst.Module) -> None:
        # Match registrations to classes, create Entrypoints
        for class_name, urls in self.resource_registrations:
            methods = self.resource_classes.get(class_name, set())
            for url in urls:
                for method in methods:
                    self.entrypoints.append(Entrypoint(...))
```

### Phase 2: Integration

1. Update `detect_flask_entrypoints()` to call both visitors
2. Merge results from decorator-based and call-based detection
3. Handle deduplication if both patterns are used

### Phase 3: Tests

Create test fixtures in `tests/fixtures/flask_restful_app/`:

```python
# tests/fixtures/flask_restful_app/app.py
from flask import Flask
from flask_restful import Api, Resource

app = Flask(__name__)
api = Api(app)

class UserResource(Resource):
    def get(self): pass
    def post(self): pass

class ItemResource(Resource):
    def get(self): pass
    def put(self): pass
    def delete(self): pass

api.add_resource(UserResource, "/api/users", "/api/v2/users")
api.add_resource(ItemResource, "/api/items/<int:item_id>")
```

Test cases:
- [ ] Detect Resource classes with HTTP methods
- [ ] Detect add_resource() calls with single URL
- [ ] Detect add_resource() calls with multiple URLs
- [ ] Handle custom API subclass methods (add_org_resource)
- [ ] Merge with decorator-based routes
- [ ] Integration test against Redash subset

### Phase 4: Validation

1. Run `bubble flask audit -d /tmp/redash-audit`
2. Verify 60+ endpoints detected (vs 9 currently)
3. Confirm KeyError bugs are found by the tool
4. Document any remaining gaps

## Complexity Estimate

| Task | Effort |
|------|--------|
| FlaskRESTfulVisitor class | 2-3 hours |
| Integration with existing detector | 1 hour |
| Test fixtures and tests | 2 hours |
| Validation against Redash | 1 hour |
| **Total** | **6-7 hours** |

## Success Criteria

- [ ] `bubble flask entrypoints -d /tmp/redash-audit` finds 60+ endpoints
- [ ] `bubble flask audit -d /tmp/redash-audit` finds the 8 KeyError bugs we identified manually
- [ ] No regression on existing Flask decorator detection
- [ ] Tests pass for all patterns above

## Files to Modify

- `bubble/integrations/flask/detector.py` - Add FlaskRESTfulVisitor
- `bubble/integrations/flask/__init__.py` - Update detect_flask_entrypoints()
- `tests/fixtures/flask_restful_app/` - New test fixtures
- `tests/test_flask_restful.py` - New test file

## Related Issues

- Redash dogfooding revealed this gap
- 8 confirmed KeyError bugs were found manually but tool missed them
- See `/private/tmp/claude-502/.../scratchpad/redash-bugs.md` for manual findings
