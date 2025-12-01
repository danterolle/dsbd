"""
API routes for the User Manager microservice.
"""
from typing import Optional, Any

from flask import Blueprint, request, jsonify
from sqlalchemy.exc import IntegrityError

import services
from models import db, User

main = Blueprint("main", __name__)


@main.route("/ping")
def ping():
    """
    A simple ping endpoint to check if the service is alive.

    Returns:
        A JSON response with the message "pong".
    """
    return jsonify({"message": "pong"}), 200


@main.route("/users", methods=["POST"])
def add_user():
    """
    Adds a new user to the database.

    The request body must be a JSON object with 'email', 'first_name', and 'last_name' fields.
    'tax_code' and 'iban' are optional.

    Returns:
        A JSON response with a success message or an error message.
    """
    data: Optional[dict[str, Any]] = request.get_json()
    if not data or "email" not in data or "first_name" not in data or "last_name" not in data:
        return jsonify({"error": "Missing required fields"}), 400

    new_user = User(
        email=data["email"],
        first_name=data["first_name"],
        last_name=data["last_name"],
        tax_code=data.get("tax_code"),
        iban=data.get("iban"),
    )

    try:
        db.session.add(new_user)
        db.session.commit()
        return jsonify({"message": "User created successfully"}), 201
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "User already exists"}), 409


@main.route("/users/<string:email>", methods=["DELETE"])
def delete_user(email: str):
    """
    Deletes a user from the database.

    Args:
        email (str): The email of the user to delete.

    Returns:
        A JSON response with a success message or an error message.
    """
    user = db.session.get(User, email)
    if not user:
        return jsonify({"error": "User not found"}), 404

    db.session.delete(user)
    db.session.commit()

    services.delete_user_interests_grpc(email)

    return jsonify({"message": "User deleted successfully"}), 200


@main.route("/users/<string:email>", methods=["GET"])
def get_user(email: str):
    """
    Gets a user by their email.

    Args:
        email (str): The email of the user to retrieve.

    Returns:
        A JSON response with the user's data or a 'not found' message.
    """
    user: Optional[User] = db.session.get(User, email)
    if user:
        return jsonify(user.to_dict()), 200
    return jsonify({"error": "User not found"}), 404


@main.route("/users", methods=["GET"])
def get_all_users():
    """
    Gets all users in the database.

    Returns:
        A JSON response with a list of all users.
    """
    users = db.session.query(User).all()
    return jsonify([user.to_dict() for user in users])
