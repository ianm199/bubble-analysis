"""Flask-RESTful test fixture with various patterns."""

from flask import Flask, request
from flask_restful import Api, Resource

app = Flask(__name__)
api = Api(app)


class UserResource(Resource):
    """Single user operations."""

    def get(self, user_id):
        return {"id": user_id}

    def put(self, user_id):
        data = request.json
        return {"id": user_id, "updated": True}

    def delete(self, user_id):
        return {"deleted": user_id}


class UserListResource(Resource):
    """User collection operations."""

    def get(self):
        return [{"id": 1}, {"id": 2}]

    def post(self):
        data = request.json
        name = data["name"]
        return {"id": 3, "name": name}


class ItemResource(Resource):
    """Item with validation that can raise KeyError."""

    def get(self, item_id):
        return {"id": item_id}

    def post(self, item_id):
        data = request.json
        value = data["required_field"]
        return {"id": item_id, "value": value}


api.add_resource(UserResource, "/api/users/<int:user_id>")
api.add_resource(UserListResource, "/api/users")
api.add_resource(ItemResource, "/api/items/<int:item_id>")
