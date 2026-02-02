"""Flask-AppBuilder views using @expose decorator."""

from errors import DatabaseError, ValidationError
from flask_appbuilder import BaseView, expose
from flask_appbuilder.api import BaseApi


class DatabaseRestApi(BaseApi):
    """REST API for database operations."""

    @expose("/<int:pk>", methods=("GET",))
    def get(self, pk: int):
        """Get a database by ID."""
        if pk < 0:
            raise ValidationError("Invalid ID")
        return {"id": pk}

    @expose("/<int:pk>/connection", methods=("GET",))
    def get_connection(self, pk: int):
        """Get database connection info."""
        return {"connection": "info"}

    @expose("/test_connection/", methods=("POST",))
    def test_connection(self):
        """Test a database connection."""
        raise DatabaseError("Connection failed")


class DashboardView(BaseView):
    """Dashboard views."""

    @expose("/")
    def index(self):
        """Dashboard index."""
        return "Dashboard"

    @expose("/stats", methods=("GET", "POST"))
    def stats(self):
        """Dashboard stats."""
        raise ValidationError("Stats unavailable")
