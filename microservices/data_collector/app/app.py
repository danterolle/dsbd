import os
import time
import threading
import requests
import grpc
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from sqlalchemy import func
from models import db, UserInterest, FlightData

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

OPENSKY_API_URL = "https://opensky-network.org/api"
OPENSKY_USER = os.environ.get("OPENSKY_USER")
OPENSKY_PASS = os.environ.get("OPENSKY_PASS")

USER_MANAGER_GRPC_HOST = 'user-manager:50051'

with app.app_context():
    db.create_all()


def check_user_exists_grpc(email):
    if not service_pb2_grpc:
        return True

    try:
        with grpc.insecure_channel(USER_MANAGER_GRPC_HOST) as channel:
            stub = service_pb2_grpc.UserServiceStub(channel)
            response = stub.CheckUserExists(service_pb2.UserRequest(email=email))
            return response.exists
    except grpc.RpcError as e:
        print(f"gRPC Error: {e}")
        return False


def fetch_flights_for_airport(airport_code, mode='arrival'):
    end_time = int(time.time())
    begin_time = end_time - 4200

    url = f"{OPENSKY_API_URL}/flights/{mode}"
    params = {
        'airport': airport_code,
        'begin': begin_time,
        'end': end_time
    }

    auth = None
    if OPENSKY_USER and OPENSKY_PASS:
        auth = (OPENSKY_USER, OPENSKY_PASS)

    try:
        response = requests.get(url, params=params, auth=auth)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"OpenSky API Error {response.status_code}: {response.text}")
            return []
    except Exception as e:
        print(f"Error fetching data: {e}")
        return []


def data_collection_job():
    while True:
        print("Starting data collection cycle...")
        with app.app_context():
            interests = db.session.query(UserInterest.airport_code).distinct().all()
            unique_airports = [i[0] for i in interests]

            for airport in unique_airports:
                print(f"Processing airport: {airport}")

                arrivals = fetch_flights_for_airport(airport, 'arrival')
                save_flight_data(arrivals, airport, is_arrival=True)

                departures = fetch_flights_for_airport(airport, 'departure')
                save_flight_data(departures, airport, is_arrival=False)

        print("Cycle finished. Sleeping for 1 hour...")
        time.sleep(3600)


def save_flight_data(flights_json, airport_code=None, is_arrival=None):
    for f in flights_json:
        icao24 = f.get('icao24')
        first_seen = datetime.fromtimestamp(f.get('firstSeen'))

        existing = db.session.query(FlightData).filter_by(
            icao24=icao24,
            first_seen=first_seen
        ).first()

        if not existing:
            flight = FlightData(
                icao24=icao24,
                first_seen=first_seen,
                est_departure_airport=f.get('estDepartureAirport'),
                last_seen=datetime.fromtimestamp(f.get('lastSeen')),
                est_arrival_airport=f.get('estArrivalAirport'),
                callsign=f.get('callsign'),
                est_departure_airport_horiz_distance=f.get('estDepartureAirportHorizDistance'),
                est_departure_airport_vert_distance=f.get('estDepartureAirportVertDistance'),
                est_arrival_airport_horiz_distance=f.get('estArrivalAirportHorizDistance'),
                est_arrival_airport_vert_distance=f.get('estArrivalAirportVertDistance'),
                departure_airport_candidates_count=f.get('departureAirportCandidatesCount'),
                arrival_airport_candidates_count=f.get('arrivalAirportCandidatesCount')
            )
            db.session.add(flight)

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"DB Error saving flights: {e}")

@app.route('/interests', methods=['POST'])
def add_interest():
    data = request.get_json()
    email = data.get('email')
    airport_code = data.get('airport_code')

    if not email or not airport_code:
        return jsonify({'error': 'Missing email or airport_code'}), 400

    if not check_user_exists_grpc(email):
        return jsonify({'error': 'User does not exist'}), 404

    interest = UserInterest(user_email=email, airport_code=airport_code)
    db.session.add(interest)
    try:
        db.session.commit()
        return jsonify({'message': 'Interest added'}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/flights/last/<string:airport_code>', methods=['GET'])
def get_last_flight(airport_code):
    mode = request.args.get('mode', 'arrival')

    query = db.session.query(FlightData)
    if mode == 'arrival':
        query = query.filter(FlightData.est_arrival_airport == airport_code)
        query = query.order_by(FlightData.last_seen.desc())
    else:
        query = query.filter(FlightData.est_departure_airport == airport_code)
        query = query.order_by(FlightData.first_seen.desc())

    flight = query.first()

    if flight:
        return jsonify({
            'callsign': flight.callsign,
            'icao24': flight.icao24,
            'time': flight.last_seen if mode == 'arrival' else flight.first_seen,
            'from': flight.est_departure_airport,
            'to': flight.est_arrival_airport
        })
    return jsonify({'message': 'No flights found'}), 404


@app.route('/stats/average/<string:airport_code>', methods=['GET'])
def get_average_flights(airport_code):
    days = int(request.args.get('days', 7))
    mode = request.args.get('mode', 'arrival')

    cutoff_date = datetime.now() - timedelta(days=days)

    query = db.session.query(func.count(FlightData.id))

    if mode == 'arrival':
        query = query.filter(FlightData.est_arrival_airport == airport_code)
        query = query.filter(FlightData.last_seen >= cutoff_date)
    else:
        query = query.filter(FlightData.est_departure_airport == airport_code)
        query = query.filter(FlightData.first_seen >= cutoff_date)

    total_flights = query.scalar()
    average = total_flights / days if days > 0 else 0

    return jsonify({
        'airport': airport_code,
        'mode': mode,
        'days_analyzed': days,
        'total_flights': total_flights,
        'average_per_day': average
    })


if __name__ == "__main__":
    collector_thread = threading.Thread(target=data_collection_job)
    collector_thread.daemon = True
    collector_thread.start()

    app.run(host='0.0.0.0', port=5000, debug=True)