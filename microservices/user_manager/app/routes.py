"""
API routes for the User Manager microservice.
"""

import json
from typing import Optional, Any

from flask import Blueprint, request, jsonify
from sqlalchemy.exc import IntegrityError

import services
from models import db, User, IdempotencyKey
from metrics import track_requests, metrics_endpoint

main = Blueprint("main", __name__)

# Prometheus metrics endpoint.
@main.route("/metrics")
def metrics():
    return metrics_endpoint()

@main.route("/ping")
@track_requests
def ping():
    """
    A simple ping endpoint to check if the service is alive.
    Returns:
        A JSON response with the message "pong".
    """
    return jsonify({"message": "pong"}), 200


@main.route("/users", methods=["POST"])
@track_requests
def add_user():
    """
    Adds a new user to the database with idempotency check.
    The request body must be a JSON object with user data.
    The 'Idempotency-Key' header is required.
    Returns:
        A JSON response with a success message or an error message.
    """
    idempotency_key = request.headers.get("Idempotency-Key")
    if not idempotency_key:
        return jsonify({"error": "Idempotency-Key header is required"}), 400

    existing_key = db.session.get(IdempotencyKey, idempotency_key)
    if existing_key:
        if existing_key.status == "completed":
            return (
                jsonify(json.loads(existing_key.response_body)),
                existing_key.response_code,
            )
        elif existing_key.status == "in-progress":
            return (
                jsonify(
                    {
                        "error": "Request with this Idempotency-Key is already in progress"
                    }
                ),
                409,
            )

    data: Optional[dict[str, Any]] = request.get_json()
    if (
        not data
        or "email" not in data
        or "first_name" not in data
        or "last_name" not in data
    ):
        return jsonify({"error": "Missing required fields"}), 400

    new_key = IdempotencyKey(key=idempotency_key, user_email=data["email"])
    db.session.add(new_key)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return (
            jsonify(
                {
                    "error": "Failed to create idempotency key. Possibly a race condition."
                }
            ),
            409,
        )

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
        response_body = {"message": "User created successfully"}
        response_code = 201
    except IntegrityError:
        db.session.rollback()
        response_body = {"error": "User already exists"}
        response_code = 409

    existing_key = db.session.get(IdempotencyKey, idempotency_key)
    existing_key.response_body = json.dumps(response_body)
    existing_key.response_code = response_code
    existing_key.status = "completed"
    db.session.commit()

    return jsonify(response_body), response_code


@main.route("/users/telegram", methods=["POST"])
@track_requests
def add_telegram_chat_id():
    """
    Associates a Telegram chat ID with a user.

    The request body must be a JSON object with 'email' and 'telegram_chat_id'.

    Returns:
        A JSON response with a success message or an error message.
    """
    data: Optional[dict[str, Any]] = request.get_json()
    if not data or "email" not in data or "telegram_chat_id" not in data:
        return jsonify({"error": "Missing email or telegram_chat_id"}), 400

    email = data["email"]
    telegram_chat_id = data["telegram_chat_id"]

    user = db.session.get(User, email)
    if not user:
        return jsonify({"error": "User not found"}), 404

    user.telegram_chat_id = telegram_chat_id
    try:
        db.session.commit()
        return jsonify({"message": "Telegram chat ID updated successfully"}), 200
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "Telegram chat ID is already in use"}), 409
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@main.route("/users/<string:email>", methods=["DELETE"])
@track_requests
def delete_user(email: str):
    """
    Deletes a user from the database with idempotency check.
    Args:
        email (str): The email of the user to delete.
    Returns:
        A JSON response with a success message or an error message.
    """
    idempotency_key = request.headers.get("Idempotency-Key")
    if not idempotency_key:
        return jsonify({"error": "Idempotency-Key header is required"}), 400

    existing_key = db.session.get(IdempotencyKey, idempotency_key)
    if existing_key:
        if existing_key.status == "completed":
            return (
                jsonify(json.loads(existing_key.response_body)),
                existing_key.response_code,
            )
        elif existing_key.status == "in-progress":
            return (
                jsonify(
                    {
                        "error": "Request with this Idempotency-Key is already in progress"
                    }
                ),
                409,
            )

    new_key = IdempotencyKey(key=idempotency_key, user_email=email)
    db.session.add(new_key)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return (
            jsonify(
                {
                    "error": "Failed to create idempotency key. Possibly a race condition."
                }
            ),
            409,
        )

    user = db.session.get(User, email)
    if not user:
        response_body = {"error": "User not found"}
        response_code = 404
    else:
        db.session.delete(user)
        db.session.commit()
        services.delete_user_interests_grpc(email)
        response_body = {"message": "User deleted successfully"}
        response_code = 200

    existing_key = db.session.get(IdempotencyKey, idempotency_key)
    existing_key.response_body = json.dumps(response_body)
    existing_key.response_code = response_code
    existing_key.status = "completed"
    db.session.commit()

    return jsonify(response_body), response_code


@main.route("/users/<string:email>", methods=["GET"])
@track_requests
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
@track_requests
def get_all_users():
    """
    Gets all users in the database.
    Returns:
        A JSON response with a list of all users.
    """
    users = db.session.query(User).all()
    return jsonify([user.to_dict() for user in users])
