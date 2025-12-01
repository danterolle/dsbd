"""
Creates and configures the Flask application, initializes the database,
registers the API routes, and starts the background threads for the data
collection job and the gRPC server.
"""

import threading
from flask import Flask
from dotenv import load_dotenv

from config import DATABASE_URL
from models import db
from routes import main as main_blueprint
from grpc_server import serve_grpc
from services import data_collection_job


def create_app():
    """
    Creates and configures the Flask application.

    Init the Flask app, configures the database,
    creates the database tables, and registers the API routes.

    Returns:
        Flask: The configured Flask application instance.
    """
    load_dotenv()
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)

    with app.app_context():
        db.create_all()

    app.register_blueprint(main_blueprint)

    return app


app = create_app()

if __name__ == "__main__":
    collector_thread = threading.Thread(target=data_collection_job, daemon=True)
    grpc_thread = threading.Thread(target=serve_grpc, daemon=True)

    with app.app_context():
        collector_thread.start()
        grpc_thread.start()

    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)
