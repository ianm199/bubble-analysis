"""Flask app with global Exception handler to test builtin hierarchy."""

from flask import Flask

app = Flask(__name__)


@app.route("/users", methods=["POST"])
def create_user():
    validate_input()
    return {"id": 1}


@app.route("/items/<int:id>")
def get_item(item_id):
    if item_id < 0:
        raise ValueError("Invalid ID")
    return {"id": item_id}


@app.errorhandler(Exception)
def handle_all_errors(e):
    return {"error": str(e)}, 500


def validate_input():
    raise KeyError("Missing required field")
