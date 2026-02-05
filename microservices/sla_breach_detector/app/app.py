import logging
import time
from flask import Flask
from routes import register_routes
from services import sla_service

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def create_app():
    app = Flask(__name__)
    register_routes(app)
    return app

app = create_app()

if __name__ == '__main__':
    # Start the background scheduler
    sla_service.start_scheduler()
    time.sleep(2)
    
    app.run(host='0.0.0.0', port=5000)