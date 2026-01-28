from flask import Flask

from errors import ValidationError

app = Flask(__name__)


@app.route("/health")
def health():
    return {"status": "ok"}


@app.route("/validate", methods=["POST"])
def validate():
    raise ValidationError("Invalid input")
