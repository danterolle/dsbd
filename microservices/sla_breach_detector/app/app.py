"""
SLA Breach Detector Microservice.

Monitors GAUGE metrics via Prometheus and detects SLA violations.
"""

import logging
import os
import requests
import yaml
from flask import Flask
from prometheus_client import Counter

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

config = {}
history = {}
breach_stats = {}

CONFIG_PATH = os.environ.get("CONFIG_PATH", "config.yaml")

# Prometheus metrics
SERVICE_NAME = "sla_breach_detector"
sla_checks_total = Counter("sla_checks_total", "Total SLA check cycles", ["service"])
sla_breaches_total = Counter("sla_breaches_total", "Total breaches detected", ["service", "metric_name", "breach_type"])


def get_prometheus_scrape_interval():
    prom_url = config.get('settings', {}).get('prometheus_url', 'http://prometheus:9090')
    try:
        response = requests.get(f"{prom_url}/api/v1/status/config", timeout=5)
        if response.status_code == 200:
            config_yaml = response.json().get('data', {}).get('yaml', '')
            prom_config = yaml.safe_load(config_yaml)
            scrape_str = prom_config.get('global', {}).get('scrape_interval', '15s')
            if scrape_str.endswith('s'):
                return float(scrape_str[:-1])
            elif scrape_str.endswith('m'):
                return float(scrape_str[:-1]) * 60
    except Exception as e:
        logger.warning(f"Could not fetch Prometheus scrape interval: {e}")
    return 15.0


def load_config():
    global config
    try:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, 'r') as f:
                config = yaml.safe_load(f)
        else:
            config = {
                "metrics": [],
                "settings": {
                    "t_check": 80,
                    "prometheus_url": "http://prometheus:9090",
                    "kafka_bootstrap_servers": "kafka:9092",
                    "kafka_topic": "sla_breach"
                }
            }

        for metric in config.get('metrics', []):
            name = metric['name']
            metric_type = metric.get('type', 'gauge').lower()
            if metric_type != 'gauge':
                logger.warning(f"Metric '{name}' type '{metric_type}' is not GAUGE, skipping")
                continue
            if name not in breach_stats:
                breach_stats[name] = {"min": 0, "max": 0}
            if name not in history:
                history[name] = []
        logger.info("Configuration loaded successfully")
    except Exception as e:
        logger.error(f"Failed to load config: {e}")


load_config()

producer = None


def get_kafka_producer():
    global producer
    if producer is None:
        try:
            from kafka import KafkaProducer
            import json
            bootstrap_servers = config.get('settings', {}).get('kafka_bootstrap_servers', 'kafka:9092')
            producer = KafkaProducer(
                bootstrap_servers=bootstrap_servers,
                value_serializer=lambda v: json.dumps(v).encode('utf-8'),
                acks='all',
                retries=5
            )
            logger.info("Kafka producer initialized")
        except Exception as e:
            logger.error(f"Failed to init Kafka producer: {e}")
    return producer


def check_sla():
    import time
    logger.info("Running SLA check cycle...")
    sla_checks_total.labels(service=SERVICE_NAME).inc()
    
    prom_url = config.get('settings', {}).get('prometheus_url', 'http://prometheus:9090')
    metrics = config.get('metrics', [])

    for metric in metrics:
        if metric.get('type', 'gauge').lower() != 'gauge':
            continue
            
        name = metric['name']
        query = metric['query']
        min_val = metric['min']
        max_val = metric['max']

        try:
            response = requests.get(f"{prom_url}/api/v1/query", params={'query': query}, timeout=10)
            data = response.json()

            if data['status'] == 'success' and data['data']['result']:
                val_str = data['data']['result'][0]['value'][1]
                value = float(val_str)
                timestamp = data['data']['result'][0]['value'][0]

                if name not in history:
                    history[name] = []
                history[name].append((timestamp, value))

                if len(history[name]) > 10:
                    history[name].pop(0)

                samples = history[name]
                low_violations = [v for t, v in samples if v < min_val]
                high_violations = [v for t, v in samples if v > max_val]

                breach_type = None
                if len(low_violations) >= 3:
                    breach_type = "low"
                elif len(high_violations) >= 3:
                    breach_type = "high"

                if breach_type:
                    logger.warning(
                        f"SLA Breach detected for {name}: {breach_type} threshold violated "
                        f"({len(low_violations) if breach_type == 'low' else len(high_violations)} samples)")

                    if name not in breach_stats:
                        breach_stats[name] = {"min": 0, "max": 0}

                    if breach_type == "low":
                        breach_stats[name]["min"] += 1
                        val_violated = low_violations[-1]
                        threshold = min_val
                    else:
                        breach_stats[name]["max"] += 1
                        val_violated = high_violations[-1]
                        threshold = max_val

                    sla_breaches_total.labels(service=SERVICE_NAME, metric_name=name, breach_type=breach_type).inc()

                    prod = get_kafka_producer()
                    if prod:
                        topic = config.get('settings', {}).get('kafka_topic', 'sla_breach')
                        message = {
                            "timestamp": time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(timestamp)),
                            "metric": name,
                            "query": query,
                            "observed_value": val_violated,
                            "threshold_violated": threshold,
                            "breach_type": breach_type,
                            "violations_count": breach_stats[name]["min"] if breach_type == "low" else breach_stats[name]["max"]
                        }
                        prod.send(topic, message)
                        logger.info(f"Notification sent to Kafka topic {topic}")

                    history[name] = []
            else:
                logger.debug(f"No result for query {query}")

        except Exception as e:
            logger.error(f"Error checking SLA for {name}: {e}")


from apscheduler.schedulers.background import BackgroundScheduler
scheduler = BackgroundScheduler()


def start_scheduler():
    t_check = config.get('settings', {}).get('t_check', 80)
    scheduler.add_job(check_sla, 'interval', seconds=t_check, id='sla_job', replace_existing=True)
    if not scheduler.running:
        scheduler.start()
    logger.info(f"Scheduler started with t_check={t_check}s")


start_scheduler()


from flask import jsonify, request
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST


@app.route('/metrics')
def metrics():
    return generate_latest(), 200, {"Content-Type": CONTENT_TYPE_LATEST}


@app.route('/sla/config', methods=['GET'])
def get_config():
    return jsonify(config)


@app.route('/sla/config', methods=['POST'])
def update_config():
    global config
    new_config = request.json
    if not new_config:
        return jsonify({"error": "Invalid JSON"}), 400

    t_check = new_config.get('settings', {}).get('t_check', 0)
    t_scrape = get_prometheus_scrape_interval()
    if t_check < 5 * t_scrape:
        return jsonify({
            "error": "Constraint violation",
            "message": f"T_check ({t_check}) must be >= 5 * T_scrape ({t_scrape})"
        }), 400

    for metric in new_config.get('metrics', []):
        metric_type = metric.get('type', 'gauge').lower()
        if metric_type != 'gauge':
            return jsonify({
                "error": "Invalid metric type",
                "message": f"Metric '{metric['name']}' must be type 'gauge', got '{metric_type}'"
            }), 400

    config = new_config
    try:
        with open(CONFIG_PATH, 'w') as f:
            yaml.dump(config, f)
    except Exception as e:
        logger.error(f"Failed to save config: {e}")

    for metric in config.get('metrics', []):
        name = metric['name']
        if name not in breach_stats:
            breach_stats[name] = {"min": 0, "max": 0}
        if name not in history:
            history[name] = []

    start_scheduler()
    return jsonify({"status": "updated", "config": config})


@app.route('/breach/stats', methods=['GET'])
def get_stats():
    return jsonify(breach_stats)


@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok", "scheduler_running": scheduler.running})


@app.route('/ping', methods=['GET'])
def ping():
    return jsonify({"message": "pong"})


if __name__ == '__main__':
    import time
    time.sleep(5)
    app.run(host='0.0.0.0', port=5000)