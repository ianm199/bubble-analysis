"""DRF views fixture for testing implicit dispatch."""

from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet
from rest_framework.response import Response


class UserAPIView(APIView):
    """A simple APIView with get and post methods."""

    def get(self, request):
        data = self.validate_request(request)
        return Response(data)

    def post(self, request):
        self.process_data(request.data)
        return Response({"status": "created"})

    def validate_request(self, request):
        if not request.query_params.get("token"):
            raise ValueError("Missing token")
        return {"valid": True}

    def process_data(self, data):
        if not data:
            raise ValueError("Empty data")


class ItemViewSet(ModelViewSet):
    """A ViewSet with DRF action methods."""

    def list(self, request):
        items = self.get_items()
        return Response(items)

    def retrieve(self, request, pk=None):
        item = self.get_item(pk)
        return Response(item)

    def create(self, request):
        self.validate_item(request.data)
        return Response({"id": 1})

    def get_items(self):
        return []

    def get_item(self, pk):
        if pk is None:
            raise KeyError("Item not found")
        return {"id": pk}

    def validate_item(self, data):
        if "name" not in data:
            raise ValueError("Missing name field")
