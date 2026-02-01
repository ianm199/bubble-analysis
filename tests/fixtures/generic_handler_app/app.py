"""Flask app with generic Exception handler."""

from flask import Flask

from errors import AppError, ValidationError, UnknownError

app = Flask(__name__)


@app.route("/users", methods=["POST"])
def create_user():
    validate_input()
    return {"id": 1}


@app.route("/data")
def get_data():
    raise UnknownError("Something unexpected")


@app.errorhandler(AppError)
def handle_app_error(e):
    return {"error": str(e)}, 400


@app.errorhandler(Exception)
def handle_generic(e):
    return {"error": "Internal error"}, 500


def validate_input():
    raise ValidationError("Missing required field")
