"""
API routes for the Data Collector microservice.
"""

import threading
from typing import Optional, Any

from flask import Blueprint, request, jsonify
from sqlalchemy import func

import services
from models import db, UserInterest, FlightData
from metrics import track_requests, metrics_endpoint


main = Blueprint("main", __name__)

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


@main.route("/interests", methods=["POST"])
@track_requests
def add_interest():
    """
    Adds a new user interest and triggers data fetch for the specified airport.

    The request body must be a JSON object with 'email' and 'airport_code' fields.
    It can also optionally include 'high_value' and 'low_value' thresholds.

    Returns:
        A JSON response with a success message or an error message.
    """
    data: dict[str, Any] = request.get_json()
    email: Optional[str] = data.get("email")
    airport_code: Optional[str] = data.get("airport_code")
    high_value: Optional[int] = data.get("high_value")
    low_value: Optional[int] = data.get("low_value")

    if not email or not airport_code:
        return jsonify({"error": "Missing email or airport_code"}), 400

    if high_value is not None and low_value is not None and high_value <= low_value:
        return jsonify({"error": "high_value must be greater than low_value"}), 400

    if not services.check_user_exists_grpc(email):
        return jsonify({"error": "User does not exist"}), 404

    existing_interest = (
        db.session.query(UserInterest)
        .filter_by(user_email=email, airport_code=airport_code)
        .first()
    )
    if existing_interest:
        return jsonify({"message": "Interest already exists"}), 200

    interest = UserInterest(
        user_email=email,
        airport_code=airport_code,
        high_value=high_value,
        low_value=low_value,
    )
    db.session.add(interest)
    try:
        db.session.commit()
        from app import app

        fetch_thread = threading.Thread(
            target=services.fetch_and_store_flights, args=(airport_code, app)
        )
        fetch_thread.start()
        return jsonify({"message": "Interest added and data fetch initiated"}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@main.route("/interests", methods=["PUT"])
@track_requests
def update_interest():
    """
    Updates the high and low value thresholds for an existing user interest.

    The request body must be a JSON object with 'email', 'airport_code',
    and at least one of 'high_value' or 'low_value'.

    Returns:
        A JSON response with a success message or an error message.
    """
    data: dict[str, Any] = request.get_json()
    email: Optional[str] = data.get("email")
    airport_code: Optional[str] = data.get("airport_code")
    high_value: Optional[int] = data.get("high_value")
    low_value: Optional[int] = data.get("low_value")

    if not email or not airport_code:
        return jsonify({"error": "Missing email or airport_code"}), 400

    if high_value is None and low_value is None:
        return (
            jsonify({"error": "At least one of high_value or low_value is required"}),
            400,
        )

    interest: Optional[UserInterest] = (
        db.session.query(UserInterest)
        .filter_by(user_email=email, airport_code=airport_code)
        .first()
    )

    if not interest:
        return jsonify({"error": "Interest not found"}), 404

    if high_value is not None:
        interest.high_value = high_value
    if low_value is not None:
        interest.low_value = low_value

    if (
        interest.high_value is not None
        and interest.low_value is not None
        and interest.high_value <= interest.low_value
    ):
        return jsonify({"error": "high_value must be greater than low_value"}), 400

    try:
        db.session.commit()
        return jsonify({"message": "Interest updated successfully"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@main.route("/interests", methods=["DELETE"])
@track_requests
def remove_interest():
    """
    Removes a user interest and triggers cleanup if necessary.

    The request body must be a JSON object with 'email' and 'airport_code' fields.

    Returns:
        A JSON response with a success message or an error message.
    """
    data: dict[str, Any] = request.get_json()
    email: Optional[str] = data.get("email")
    airport_code: Optional[str] = data.get("airport_code")

    if not email or not airport_code:
        return jsonify({"error": "Missing email or airport_code"}), 400

    if not services.check_user_exists_grpc(email):
        return jsonify({"error": "User does not exist"}), 404

    interest = (
        db.session.query(UserInterest)
        .filter_by(user_email=email, airport_code=airport_code)
        .first()
    )

    if not interest:
        return jsonify({"error": "Interest not found"}), 404

    db.session.delete(interest)
    try:
        db.session.commit()
        from app import app

        cleanup_thread = threading.Thread(
            target=services.cleanup_airport_data, args=(airport_code, app)
        )
        cleanup_thread.start()
        return (
            jsonify({"message": "Interest removed and cleanup initiated"}),
            200,
        )
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@main.route("/interests/<string:email>", methods=["GET"])
def get_user_interests(email: str):
    """
    Gets all airport interests for a user, including thresholds.

    Args:
        email (str): The email of the user.

    Returns:
        A JSON response with the user's email and a list of their interests.
    """
    if not services.check_user_exists_grpc(email):
        return jsonify({"error": "User does not exist"}), 404

    interests: list[UserInterest] = (
        db.session.query(UserInterest).filter_by(user_email=email).all()
    )
    user_interests = [
        {
            "airport_code": interest.airport_code,
            "high_value": interest.high_value,
            "low_value": interest.low_value,
        }
        for interest in interests
    ]
    return jsonify({"email": email, "interests": user_interests}), 200


@main.route("/flights/<string:airport_code>", methods=["GET"])
@track_requests
def get_flights(airport_code: str):
    """
    Gets flights for a specific airport.

    The 'type' query parameter can be used to filter by 'arrivals' or 'departures'.
    If not provided, all flights for the airport are returned.

    Args:
        airport_code (str): The ICAO code of the airport.

    Returns:
        A JSON response with a list of flights or a 'not found' message.
    """
    flight_type = request.args.get("type")

    query = db.session.query(FlightData)
    if flight_type == "arrivals":
        query = query.filter(FlightData.est_arrival_airport == airport_code)
        flights: Optional[list[FlightData]] = query.order_by(
            FlightData.last_seen.desc()
        ).all()
    elif flight_type == "departures":
        query = query.filter(FlightData.est_departure_airport == airport_code)
        flights: Optional[list[FlightData]] = query.order_by(
            FlightData.first_seen.desc()
        ).all()
    else:
        query = query.filter(
            (FlightData.est_arrival_airport == airport_code)
            | (FlightData.est_departure_airport == airport_code)
        )
        flights: Optional[list[FlightData]] = query.all()

    if flights:
        return jsonify([flight.to_dict() for flight in flights])
    return jsonify({"message": "No flights found"}), 404


@main.route("/flights/average/<string:icao>", methods=["GET"])
@track_requests
def get_average_flights(icao: str):
    """
    Calculates the average number of flights per day for a given airport.

    Args:
        icao (str): The ICAO code of the airport.

    Returns:
        A JSON response with the airport ICAO and the average number of flights per day.
    """
    flights_query = db.session.query(FlightData).filter(
        (FlightData.est_arrival_airport == icao)
        | (FlightData.est_departure_airport == icao)
    )

    total_flights = flights_query.count()

    if total_flights == 0:
        return jsonify({"message": f"No flights found for airport {icao}"}), 404

    distinct_days = flights_query.with_entities(
        func.count(func.distinct(func.date(FlightData.first_seen)))
    ).scalar()

    if distinct_days == 0:
        average = 0
    else:
        average = total_flights / distinct_days

    return jsonify({"airport": icao, "average_flights_per_day": average})


@main.route("/flights/last/<string:icao>", methods=["GET"])
@track_requests
def get_last_flight(icao: str):
    """
    Returns the last flight for a given airport (most recent last_seen).

    Args:
        icao (str): The ICAO code of the airport.

    Returns:
        A JSON response with the last flight data or a 'not found' message.
    """
    last_flight = (
        db.session.query(FlightData)
        .filter(
            (FlightData.est_arrival_airport == icao)
            | (FlightData.est_departure_airport == icao)
        )
        .order_by(FlightData.last_seen.desc())
        .first()
    )

    if last_flight:
        return jsonify(last_flight.to_dict())
    else:
        return jsonify({"message": f"No flights found for airport {icao}"}), 404
