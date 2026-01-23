"""This script contains the business logic for the Data Collector microservice.

It includes functions for interacting with the OpenSky API, handling gRPC calls,
and managing the data collection process.
"""

import os
import time
import json
import requests
import grpc
from datetime import datetime
from typing import Optional
from pybreaker import CircuitBreaker, CircuitBreakerError

from flask import current_app
from sqlalchemy import tuple_
from kafka import KafkaProducer

from models import db, UserInterest, FlightData
from config import (
    OPENSKY_API_URL,
    TOKEN_URL,
    USER_MANAGER_GRPC_HOST,
    KAFKA_BROKER_URL,
    KAFKA_TOPIC,
)

import service_pb2
import service_pb2_grpc

from metrics import track_opensky_call, track_flights_fetched


cached_token = None
cached_expiry = 0

# Create a circuit breaker
breaker = CircuitBreaker(fail_max=5, reset_timeout=60)

# Create a Kafka producer
producer = KafkaProducer(
    bootstrap_servers=KAFKA_BROKER_URL,
    value_serializer=lambda v: json.dumps(v).encode("utf-8"),
)


def send_alert_to_kafka(airport_code: str, flight_count: int) -> None:
    """
    Sends an alert to Kafka for each user interested in the airport.

    Args:
        airport_code (str): The airport code.
        flight_count (int): The number of flights.
    """
    with current_app.app_context():
        interests = UserInterest.query.filter_by(airport_code=airport_code).all()
        for interest in interests:
            if interest.high_value is not None or interest.low_value is not None:
                message = {
                    "user_email": interest.user_email,
                    "airport_code": interest.airport_code,
                    "flight_count": flight_count,
                    "high_value": interest.high_value,
                    "low_value": interest.low_value,
                }
                producer.send(KAFKA_TOPIC, message)
                print(f"Sent message to Kafka: {message}")


def get_opensky_token() -> Optional[str]:
    """
    Fetches and caches the OpenSky API token.

    Returns:
        The cached or newly fetched token, or None if an error occurs.
    """
    global cached_token, cached_expiry

    if cached_token and time.time() < cached_expiry:
        return cached_token

    client_id = os.getenv("OPEN_SKY_CLIENT_ID")
    client_secret = os.getenv("OPEN_SKY_CLIENT_SECRET")

    data = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
    }

    try:
        response = requests.post(TOKEN_URL, data=data)
        response.raise_for_status()
        token_data = response.json()

        cached_token = token_data["access_token"]
        cached_expiry = time.time() + token_data["expires_in"] - 30

        return cached_token
    except requests.exceptions.RequestException as e:
        print(f"Error getting OpenSky token: {e}")
        return None


@breaker
def call_opensky(api_url: str, params: Optional[dict] = None) -> Optional[dict]:
    """
    Makes an authenticated call to the OpenSky API, protected by a circuit breaker.

    Args:
        api_url (str): The URL of the API endpoint to call.
        params (dict, optional): A dictionary of query parameters. Defaults to None.

    Returns:
        The JSON response from the API, or None if an error occurs.
    """
    token = get_opensky_token()
    if not token:
        return None
    headers = {"Authorization": f"Bearer {token}"}
    try:
        response = requests.get(api_url, headers=headers, params=params)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error calling OpenSky API: {e}")
        raise  

def get_grpc_stub() -> Optional[service_pb2_grpc.UserServiceStub]:
    """
    Creates and returns a gRPC stub for the User Manager service.

    Returns:
        A gRPC stub for the User Manager service, or None if the host is not set.
    """
    if not USER_MANAGER_GRPC_HOST:
        return None
    grpc_channel = grpc.insecure_channel(USER_MANAGER_GRPC_HOST)
    return service_pb2_grpc.UserServiceStub(grpc_channel)


def check_user_exists_grpc(email: str) -> bool:
    """
    Checks if a user exists via gRPC call to User Manager service.
    In case of gRPC error, assume the user exists to avoid blocking.

    Args:
        email (str): The email of the user to check.

    Returns:
        True if the user exists, False otherwise.
    """
    grpc_stub = get_grpc_stub()
    if not grpc_stub:
        return True

    try:
        response = grpc_stub.CheckUserExists(service_pb2.UserRequest(email=email))
        return response.exists
    except grpc.RpcError as e:
        print(f"gRPC Error: {e}")
        return True


def fetch_and_store_flights(airport_code: str, app) -> None:
    """
    Fetches and stores the last 24 hours of flights for a given airport.

    Args:
        airport_code (str): The ICAO code of the airport.
        app: The Flask application instance.
    """
    print(f"Fetching flights for airport: {airport_code}")
    end_time = int(time.time())
    begin_time = end_time - 24 * 60 * 60

    url = f"{OPENSKY_API_URL}/flights/all"
    params = {"airport": airport_code, "begin": begin_time, "end": end_time}

    start_time = time.time()
    success = False

    try:
        flights = call_opensky(url, params=params)
        duration = time.time() - start_time

        if flights is not None:
            flight_count = len(flights)
            print(f"Found {flight_count} flights for {airport_code}.")

            track_opensky_call(airport_code, duration, success=True)
            track_flights_fetched(airport_code, flight_count)

            if app:
                with app.app_context():
                    save_flight_data(flights)
                    send_alert_to_kafka(airport_code, flight_count)
            else:
                save_flight_data(flights)
                send_alert_to_kafka(airport_code, flight_count)
        else:
            track_opensky_call(airport_code, duration, success=True)
            track_flights_fetched(airport_code, 0)
            print(f"No flights found for {airport_code} in the last 24 hours.")
    except CircuitBreakerError:
        duration = time.time() - start_time
        track_opensky_call(airport_code, duration, success=False)
        print("Circuit breaker is open. Skipping OpenSky API call.")
    except Exception as e:
        duration = time.time() - start_time
        track_opensky_call(airport_code, duration, success=False)
        print(f"Error fetching flights for {airport_code}: {e}")


def data_collection_job(app) -> None:
    """Background job to periodically collect flight data for all interested airports."""
    print("Data collection job started.")
    while True:
        print("Starting data collection cycle...")
        with app.app_context():
            try:
                interests = db.session.query(UserInterest.airport_code).distinct().all()
                unique_airports: list[str] = [i[0] for i in interests]
                print(
                    f"Found {len(unique_airports)} unique airports to process: {unique_airports}"
                )

                for airport in unique_airports:
                    fetch_and_store_flights(airport, app)

            except Exception as e:
                print(f"An error occurred in the data collection job: {e}")

        print("Cycle finished. Sleeping for 5 minutes...")
        time.sleep(300)


def save_flight_data(flights: list[dict]) -> None:
    """
    Saves flight data to the database, avoiding duplicates.

    Args:
        flights (list[dict]): A list of flight data dictionaries from the OpenSky API.
    """
    if not flights:
        return

    batch_size = 100
    for i in range(0, len(flights), batch_size):
        batch = flights[i : i + batch_size]

        flight_keys = [
            (f["icao24"], datetime.fromtimestamp(f["firstSeen"])) for f in batch
        ]
        existing_flights = (
            db.session.query(FlightData)
            .filter(tuple_(FlightData.icao24, FlightData.first_seen).in_(flight_keys))
            .all()
        )
        existing_flights_map = {(f.icao24, f.first_seen): f for f in existing_flights}

        new_flights = []
        for f in batch:
            key = (f["icao24"], datetime.fromtimestamp(f["firstSeen"]))
            if key not in existing_flights_map:
                last_seen_ts: Optional[int] = f.get("lastSeen")
                if last_seen_ts is None:
                    last_seen_ts = f.get("firstSeen")
                last_seen = (
                    datetime.fromtimestamp(last_seen_ts) if last_seen_ts else None
                )

                flight = FlightData(
                    icao24=f["icao24"],
                    first_seen=datetime.fromtimestamp(f["firstSeen"]),
                    est_departure_airport=f.get("estDepartureAirport"),
                    last_seen=last_seen,
                    est_arrival_airport=f.get("estArrivalAirport"),
                    callsign=f.get("callsign"),
                    est_departure_airport_horiz_distance=f.get(
                        "estDepartureAirportHorizDistance"
                    ),
                    est_departure_airport_vert_distance=f.get(
                        "estDepartureAirportVertDistance"
                    ),
                    est_arrival_airport_horiz_distance=f.get(
                        "estArrivalAirportHorizDistance"
                    ),
                    est_arrival_airport_vert_distance=f.get(
                        "estArrivalAirportVertDistance"
                    ),
                    departure_airport_candidates_count=f.get(
                        "departureAirportCandidatesCount"
                    ),
                    arrival_airport_candidates_count=f.get(
                        "arrivalAirportCandidatesCount"
                    ),
                )
                new_flights.append(flight)

        if new_flights:
            db.session.bulk_save_objects(new_flights)

        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"DB Error saving flights for batch: {e}")


def cleanup_airport_data(airport_code: str, app) -> None:
    """
    Checks if an airport is still a favorite for any user.
    If not, deletes all flight data for that airport.

    Args:
        airport_code (str): The ICAO code of the airport to clean up.
        app: The Flask application instance.
    """
    with app.app_context():
        interest_exists = (
            db.session.query(UserInterest).filter_by(airport_code=airport_code).first()
        )

        if not interest_exists:
            print(
                f"No more interests for {airport_code}. Deleting associated flight data."
            )
            try:
                num_deleted = (
                    db.session.query(FlightData)
                    .filter(
                        (FlightData.est_arrival_airport == airport_code)
                        | (FlightData.est_departure_airport == airport_code)
                    )
                    .delete()
                )
                db.session.commit()
                print(
                    f"Deleted {num_deleted} flight data entries for airport {airport_code}."
                )
            except Exception as e:
                db.session.rollback()
                print(f"Error deleting flight data for airport {airport_code}: {e}")
