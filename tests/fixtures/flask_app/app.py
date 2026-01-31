from errors import AppError, ValidationError
from flask import Flask

app = Flask(__name__)


@app.route("/users", methods=["POST"])
def create_user():
    validate_input()
    return {"id": 1}


@app.route("/users/<int:id>")
def get_user(id):
    if id < 0:
        raise ValidationError("Invalid ID")
    return {"id": id}


@app.errorhandler(AppError)
def handle_app_error(e):
    return {"error": str(e)}, 400


def validate_input():
    raise ValidationError("Missing required field")
