"""Flask-RESTful API registrations (separate from class definitions)."""

from flask import Flask
from flask_restful import Api

from .resources import GroupResource, UserResource

app = Flask(__name__)
api = Api(app)

api.add_resource(UserResource, "/api/users/<int:user_id>")
api.add_resource(GroupResource, "/api/groups/<int:group_id>")
