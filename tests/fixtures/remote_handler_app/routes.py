"""Routes file - handlers are in a separate file."""

from flask import Flask

app = Flask(__name__)


class BalanceError(Exception):
    """Custom balance error."""
    pass


def validate_balance(amount):
    """Validate balance - can raise BalanceError."""
    if amount < 0:
        raise BalanceError("Negative balance")


@app.route("/balance", methods=["POST"])
def balance():
    """Balance endpoint - no local handler for BalanceError."""
    validate_balance(100)
    return {"status": "ok"}


@app.route("/transfer", methods=["POST"])
def transfer():
    """Transfer endpoint - also no local handler."""
    validate_balance(50)
    return {"status": "transferred"}
