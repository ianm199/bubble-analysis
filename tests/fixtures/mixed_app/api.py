from errors import ValidationError
from flask import Flask

app = Flask(__name__)


@app.route("/health")
def health():
    return {"status": "ok"}


@app.route("/validate", methods=["POST"])
def validate():
    raise ValidationError("Invalid input")
