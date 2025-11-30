import os
import time
import threading
from concurrent import futures
from typing import Optional, Any

import requests
import grpc
from datetime import datetime
from flask import Flask, request, jsonify
from sqlalchemy import func, tuple_
from sqlalchemy.orm import InstrumentedAttribute

from models import db, UserInterest, FlightData
from dotenv import load_dotenv

try:
    import service_pb2
    import service_pb2_grpc
except ImportError:
    service_pb2 = None
    service_pb2_grpc = None

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db.init_app(app)

OPENSKY_API_URL: str = "https://opensky-network.org/api"

USER_MANAGER_GRPC_HOST: str = "user-manager:50051"

grpc_channel = (
    grpc.insecure_channel(USER_MANAGER_GRPC_HOST) if service_pb2_grpc else None
)
grpc_stub = service_pb2_grpc.UserServiceStub(grpc_channel) if grpc_channel else None

with app.app_context():
    db.create_all()

load_dotenv()

TOKEN_URL = "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"

cached_token = None
cached_expiry = 0


def get_opensky_token():
    global cached_token, cached_expiry

    if cached_token and time.time() < cached_expiry:
        return cached_token

    client_id = os.getenv("OPEN_SKY_CLIENT_ID")
    client_secret = os.getenv("OPEN_SKY_CLIENT_SECRET")
    print(f"OPEN_SKY_CLIENT_ID: {client_id}")
    print(f"OPEN_SKY_CLIENT_SECRET: {client_secret}")

    data = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
    }

    response = requests.post(TOKEN_URL, data=data)
    response.raise_for_status()
    token_data = response.json()

    cached_token = token_data["access_token"]
    cached_expiry = time.time() + token_data["expires_in"] - 30

    return cached_token


def call_opensky(api_url, params=None):
    token = get_opensky_token()

    headers = {"Authorization": f"Bearer {token}"}

    response = requests.get(api_url, headers=headers, params=params)
    response.raise_for_status()  #
    return response.json()


def check_user_exists_grpc(email: str) -> bool:
    if not grpc_stub:
        return True

    try:
        response = grpc_stub.CheckUserExists(service_pb2.UserRequest(email=email))
        return response.exists
    except grpc.RpcError as e:
        print(f"gRPC Error: {e}")
        return False


def fetch_and_store_flights(airport_code: str):
    """Fetches and stores the last 24 hours of flights for a given airport."""
    print(f"Fetching flights for airport: {airport_code}")
    end_time = int(time.time())
    begin_time = end_time - 24 * 60 * 60

    url = f"{OPENSKY_API_URL}/flights/all"
    params = {"airport": airport_code, "begin": begin_time, "end": end_time}

    try:
        flights = call_opensky(url, params=params)
        print(f"OpenSky API response: {flights}")
        if flights:
            print(f"Found {len(flights)} flights for {airport_code}.")
            with app.app_context():
                save_flight_data(flights)
        else:
            print(f"No flights found for {airport_code}.")
    except requests.exceptions.HTTPError as http_err:
        if http_err.response.status_code == 404:
            print(f"No flights found for {airport_code} (404).")
        else:
            print(
                f"OpenSky API HTTP Error {http_err.response.status_code} for {airport_code}: {http_err.response.text}"
            )
    except Exception as e:
        print(f"Error fetching data for airport {airport_code}: {e}")


def data_collection_job() -> None:
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
                    fetch_and_store_flights(airport)

            except Exception as e:
                print(f"An error occurred in the data collection job: {e}")

        print("Cycle finished. Sleeping for 5 minutes...")
        time.sleep(300)


def save_flight_data(flights: list[dict]) -> None:
    if not flights:
        print("No flights to save.")
        return

    print(f"Saving {len(flights)} flights to the database.")

    batch_size = 100
    for i in range(0, len(flights), batch_size):
        batch = flights[i : i + batch_size]
        print(
            f"Processing batch {i // batch_size + 1}/{(len(flights) + batch_size - 1) // batch_size}"
        )

        flight_keys = [
            (f["icao24"], datetime.fromtimestamp(f["firstSeen"])) for f in batch
        ]
        existing_flights = (
            db.session.query(FlightData)
            .filter(tuple_(FlightData.icao24, FlightData.first_seen).in_(flight_keys))
            .all()
        )
        existing_flights_map = {(f.icao24, f.first_seen): f for f in existing_flights}
        print(
            f"Found {len(existing_flights_map)} existing flights in the database for this batch."
        )

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

        print("Attempting to commit changes to the database for batch.")
        try:
            db.session.commit()
            print(f"DB write successful for batch: {len(new_flights)} new flights.")
        except Exception as e:
            db.session.rollback()
            print(f"DB Error saving flights for batch: {e}")
            print(f"Details of the error: {e.args}")


@app.route("/ping")
def ping():
    return jsonify({"message": "pong"}), 200


@app.route("/interests", methods=["POST"])
def add_interest():
    data: dict[str, Any] = request.get_json()
    email: Optional[str] = data.get("email")
    airport_code: Optional[str] = data.get("airport_code")

    if not email or not airport_code:
        return jsonify({"error": "Missing email or airport_code"}), 400

    if not check_user_exists_grpc(email):
        return jsonify({"error": "User does not exist"}), 404

    # Check if interest already exists
    existing_interest = (
        db.session.query(UserInterest)
        .filter_by(user_email=email, airport_code=airport_code)
        .first()
    )
    if existing_interest:
        return jsonify({"message": "Interest already exists"}), 200

    interest = UserInterest(user_email=email, airport_code=airport_code)
    db.session.add(interest)
    try:
        db.session.commit()
        # Trigger immediate data fetch for the new airport in the background
        fetch_thread = threading.Thread(
            target=fetch_and_store_flights, args=(airport_code,)
        )
        fetch_thread.start()
        return jsonify({"message": "Interest added and data fetch initiated"}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


def cleanup_airport_data(airport_code: str):
    """
    Checks if an airport is still a favorite for any user.
    If not, deletes all flight data for that airport.
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


@app.route("/interests", methods=["DELETE"])
def remove_interest():
    data: dict[str, Any] = request.get_json()
    email: Optional[str] = data.get("email")
    airport_code: Optional[str] = data.get("airport_code")

    if not email or not airport_code:
        return jsonify({"error": "Missing email or airport_code"}), 400

    if not check_user_exists_grpc(email):
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
        cleanup_thread = threading.Thread(
            target=cleanup_airport_data, args=(airport_code,)
        )
        cleanup_thread.start()
        return (
            jsonify({"message": "Interest removed and cleanup initiated"}),
            200,
        )
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@app.route("/interests/<string:email>", methods=["GET"])
def get_user_interests(email: str):
    if not check_user_exists_grpc(email):
        return jsonify({"error": "User does not exist"}), 404

    interests: list[UserInterest] = (
        db.session.query(UserInterest).filter_by(user_email=email).all()
    )
    airport_codes: list[InstrumentedAttribute[str]] = [interest.airport_code for interest in interests]
    return jsonify({"email": email, "airport_codes": airport_codes}), 200


@app.route("/flights/<string:airport_code>", methods=["GET"])
def get_flights(airport_code):
    """Get flights for a specific airport."""
    flight_type = request.args.get("type")

    if flight_type == "arrivals":
        query = db.session.query(FlightData).filter(
            FlightData.est_arrival_airport == airport_code
        )
        flights: Optional[list[FlightData]] = query.order_by(
            FlightData.last_seen.desc()
        ).all()
    elif flight_type == "departures":
        query = db.session.query(FlightData).filter(
            FlightData.est_departure_airport == airport_code
        )
        flights: Optional[list[FlightData]] = query.order_by(
            FlightData.first_seen.desc()
        ).all()
    else:
        query = db.session.query(FlightData).filter(
            (FlightData.est_arrival_airport == airport_code)
            | (FlightData.est_departure_airport == airport_code)
        )
        flights: Optional[list[FlightData]] = query.all()

    if flights:
        return jsonify([flight.to_dict() for flight in flights])
    return jsonify({"message": "No flights found"}), 404


@app.route("/flights/average/<string:icao>", methods=["GET"])
def get_average_flights(icao: str):
    """Calculates the average number of flights per day for a given airport."""
    # Subquery to get all flights for the given airport (arrivals and departures)
    flights_query = db.session.query(FlightData).filter(
        (FlightData.est_arrival_airport == icao)
        | (FlightData.est_departure_airport == icao)
    )

    total_flights = flights_query.count()

    if total_flights == 0:
        return jsonify({"message": f"No flights found for airport {icao}"}), 404

    # Calculate the number of distinct days
    distinct_days = (
        flights_query.with_entities(func.count(func.distinct(func.date(FlightData.first_seen)))).scalar()
    )

    if distinct_days == 0:
        average = 0
    else:
        average = total_flights / distinct_days

    return jsonify({"airport": icao, "average_flights_per_day": average})


@app.route("/flights/last/<string:icao>", methods=["GET"])
def get_last_flight(icao: str):
    """Returns the last flight for a given airport (most recent last_seen)."""
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


class DataCollectorService(
    service_pb2_grpc.DataCollectorServiceServicer if service_pb2_grpc else object
):
    @staticmethod
    def DeleteUserInterests(self, request, context):
        with app.app_context():
            try:
                num_deleted = (
                    db.session.query(UserInterest)
                    .filter_by(user_email=request.email)
                    .delete()
                )
                db.session.commit()
                print(f"Deleted {num_deleted} interests for user {request.email}")
                return service_pb2.DeleteInterestsResponse(
                    success=True, deleted_count=num_deleted
                )
            except Exception as e:
                db.session.rollback()
                print(f"Error deleting interests for user {request.email}: {e}")
                return service_pb2.DeleteInterestsResponse(
                    success=False, deleted_count=0
                )


def serve_grpc():
    if not service_pb2_grpc:
        print("gRPC modules not found. Run protoc to generate them.")
        return

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    service_pb2_grpc.add_DataCollectorServiceServicer_to_server(
        DataCollectorService(), server
    )
    server.add_insecure_port("[::]:50052")
    print("gRPC Server starting on port 50052...")
    server.start()
    server.wait_for_termination()


if __name__ == "__main__":
    print("Starting threads...")
    collector_thread = threading.Thread(target=data_collection_job)
    collector_thread.daemon = True
    collector_thread.start()

    grpc_thread = threading.Thread(target=serve_grpc)
    grpc_thread.daemon = True
    grpc_thread.start()

    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)
