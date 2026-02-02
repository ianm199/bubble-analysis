"""Flask-RESTful Resource classes (defined separately from registration)."""

from flask import request
from flask_restful import Resource


class UserResource(Resource):
    """User operations - class defined here, registered in api.py."""

    def get(self, user_id):
        return {"id": user_id}

    def put(self, user_id):
        data = request.json
        return {"id": user_id, "updated": True}

    def delete(self, user_id):
        return {"deleted": user_id}


class GroupResource(Resource):
    """Group operations - class defined here, registered in api.py."""

    def get(self, group_id):
        return {"id": group_id}

    def post(self, group_id):
        data = request.json
        name = data["name"]
        return {"id": group_id, "name": name}
