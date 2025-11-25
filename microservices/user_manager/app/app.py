import os
import threading
from concurrent import futures
import grpc
from flask import Flask, request, jsonify
from sqlalchemy.exc import IntegrityError
from models import db, User


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

with app.app_context():
    db.create_all()

@app.route('/users', methods=['POST'])
def add_user():
    data = request.get_json()
    if not data or 'email' not in data or 'nome' not in data or 'cognome' not in data:
        return jsonify({'error': 'Missing required fields'}), 400

    new_user = User(
        email=data['email'],
        nome=data['nome'],
        cognome=data['cognome'],
        codice_fiscale=data.get('codice_fiscale'),
        iban=data.get('iban')
    )

    try:
        db.session.add(new_user)
        db.session.commit()
        return jsonify({'message': 'User created successfully'}), 201
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'User already exists'}), 409


@app.route('/users/<string:email>', methods=['DELETE'])
def delete_user(email):
    user = db.session.get(User, email)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    db.session.delete(user)
    db.session.commit()
    return jsonify({'message': 'User deleted successfully'}), 200


@app.route('/users/<string:email>', methods=['GET'])
def get_user(email):
    user = db.session.get(User, email)
    if user:
        return jsonify(user.to_dict()), 200
    return jsonify({'error': 'User not found'}), 404


class UserService(service_pb2_grpc.UserServiceServicer if service_pb2_grpc else object):
    def CheckUserExists(self, request):
        with app.app_context():
            user = db.session.get(User, request.email)
            exists = user is not None
            return service_pb2.UserResponse(exists=exists)


def serve_grpc():
    if not service_pb2_grpc:
        print("gRPC modules not found. Run protoc to generate them.")
        return

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    service_pb2_grpc.add_UserServiceServicer_to_server(UserService(), server)
    server.add_insecure_port('[::]:50051')
    print("gRPC Server starting on port 50051...")
    server.start()
    server.wait_for_termination()


if __name__ == "__main__":
    grpc_thread = threading.Thread(target=serve_grpc)
    grpc_thread.daemon = True
    grpc_thread.start()

    app.run(host='0.0.0.0', port=5000, debug=True)