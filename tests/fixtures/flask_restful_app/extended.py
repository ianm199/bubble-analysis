"""Extended Flask-RESTful patterns - custom API subclass and multiple URLs."""

from flask import Flask, request
from flask_restful import Api, Resource

app = Flask(__name__)


class CustomApi(Api):
    """Custom API extension like Redash's ApiExt."""

    def add_org_resource(self, resource, *urls, **kwargs):
        prefixed_urls = [f"/org{{org_id}}{url}" for url in urls]
        return self.add_resource(resource, *prefixed_urls, **kwargs)


api = CustomApi(app)


class QueryResource(Resource):
    """Resource with multiple URL registrations."""

    def get(self, query_id=None, result_id=None):
        return {"query_id": query_id, "result_id": result_id}

    def post(self):
        data = request.json
        query = data["query"]
        return {"query": query}


class GroupResource(Resource):
    """Resource registered via custom method."""

    def get(self, group_id):
        return {"id": group_id}

    def post(self, group_id):
        data = request.json
        name = data["name"]
        return {"id": group_id, "name": name}


api.add_resource(
    QueryResource,
    "/api/queries/<int:query_id>",
    "/api/queries/<int:query_id>/results/<int:result_id>",
    "/api/query_results",
)

api.add_org_resource(GroupResource, "/api/groups/<int:group_id>")
