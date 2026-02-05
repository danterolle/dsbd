from flask import jsonify, request
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from services import sla_service

def register_routes(app):
    @app.route('/metrics')
    def metrics():
        return generate_latest(), 200, {"Content-Type": CONTENT_TYPE_LATEST}

    @app.route('/sla/config', methods=['GET'])
    def get_config():
        return jsonify(sla_service.get_config())

    @app.route('/sla/config', methods=['POST'])
    def update_config():
        new_config = request.json
        if not new_config:
            return jsonify({"error": "Invalid JSON"}), 400

        success, message = sla_service.update_config(new_config)
        if not success:
            return jsonify({
                "error": "Update failed",
                "message": message
            }), 400

        return jsonify({"status": "updated", "config": sla_service.get_config()})

    @app.route('/breach/stats', methods=['GET'])
    def get_stats():
        return jsonify(sla_service.get_stats())

    @app.route('/health', methods=['GET'])
    def health():
        return jsonify({
            "status": "ok", 
            "scheduler_running": sla_service.scheduler.running
        })

    @app.route('/ping', methods=['GET'])
    def ping():
        return jsonify({"message": "pong"})
