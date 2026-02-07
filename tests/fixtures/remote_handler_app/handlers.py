"""Handler file - contains @errorhandler that covers routes in other files."""

from flask import jsonify
from routes import BalanceError, app


@app.errorhandler(BalanceError)
def handle_balance_error(e):
    """Global handler for BalanceError - in a different file from the routes."""
    return jsonify({"error": "Balance error occurred"}), 400


@app.errorhandler(Exception)
def handle_generic(e):
    """Generic handler catches everything."""
    return jsonify({"error": "Something went wrong"}), 500
