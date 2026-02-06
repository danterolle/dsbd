import json
import logging
import os
import time
import requests
import yaml
from apscheduler.schedulers.background import BackgroundScheduler
from kafka import KafkaProducer
from metrics import sla_checks_total, sla_breaches_total, SERVICE_NAME

logger = logging.getLogger(__name__)

class SLADetectorService:
    def __init__(self, config_path="config.yaml"):
        self.config_path = config_path
        self.config = {}
        self.history = {}
        self.breach_stats = {}
        self.scheduler = BackgroundScheduler()
        self.producer = None
        self._load_initial_config()

    def _get_kafka_producer(self):
        if self.producer is None:
            try:
                bootstrap_servers = self.config.get('settings', {}).get('kafka_bootstrap_servers', 'kafka:9092')
                self.producer = KafkaProducer(
                    bootstrap_servers=bootstrap_servers,
                    value_serializer=lambda v: json.dumps(v).encode('utf-8'),
                    acks='all',
                    retries=5
                )
                logger.info("Kafka producer initialized")
            except Exception as e:
                logger.error(f"Failed to init Kafka producer: {e}")
        return self.producer

    def _get_prometheus_scrape_interval(self):
        prom_url = self.config.get('settings', {}).get('prometheus_url', 'http://prometheus:9090')
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

    def _load_initial_config(self):
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r') as f:
                    self.config = yaml.safe_load(f)
            else:
                self.config = {
                    "metrics": [],
                    "settings": {
                        "t_check": 80,
                        "prometheus_url": "http://prometheus:9090",
                        "kafka_bootstrap_servers": "kafka:9092",
                        "kafka_topic": "sla_breach"
                    }
                }
            self._initialize_stats()
            self._validate_t_check()
            logger.info("Configuration loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load config: {e}")

    def _initialize_stats(self):
        for metric in self.config.get('metrics', []):
            name = metric['name']
            metric_type = metric.get('type', 'gauge').lower()
            if metric_type != 'gauge':
                logger.warning(f"Metric '{name}' type '{metric_type}' is not GAUGE, skipping")
                continue
            if name not in self.breach_stats:
                self.breach_stats[name] = {"min": 0, "max": 0}
            if name not in self.history:
                self.history[name] = []

    def _validate_t_check(self):
        t_check = self.config.get('settings', {}).get('t_check', 80)
        t_scrape = self._get_prometheus_scrape_interval()
        if t_check < 5 * t_scrape:
            new_t_check = 5 * t_scrape
            logger.warning(f"T_check ({t_check}) is too low relative to T_scrape ({t_scrape}). Increasing to {new_t_check}s")
            self.config['settings']['t_check'] = new_t_check

    def check_sla(self):
        logger.info("Running SLA check cycle...")
        sla_checks_total.labels(service=SERVICE_NAME).inc()

        prom_url = self.config.get('settings', {}).get('prometheus_url', 'http://prometheus:9090')
        metrics = self.config.get('metrics', [])

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

                    if name not in self.history:
                        self.history[name] = []
                    self.history[name].append((timestamp, value))

                    if len(self.history[name]) > 10:
                        self.history[name].pop(0)

                    samples = self.history[name]
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
                            f"({len(low_violations) if breach_type == 'low' else len(high_violations)} samples)"
                        )

                        if name not in self.breach_stats:
                            self.breach_stats[name] = {"min": 0, "max": 0}

                        if breach_type == "low":
                            self.breach_stats[name]["min"] += 1
                            val_violated = low_violations[-1]
                            threshold = min_val
                        else:
                            self.breach_stats[name]["max"] += 1
                            val_violated = high_violations[-1]
                            threshold = max_val

                        sla_breaches_total.labels(service=SERVICE_NAME, metric_name=name, breach_type=breach_type).inc()

                        prod = self._get_kafka_producer()
                        if prod:
                            topic = self.config.get('settings', {}).get('kafka_topic', 'sla_breach')
                            message = {
                                "timestamp": time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(timestamp)),
                                "metric": name,
                                "query": query,
                                "observed_value": val_violated,
                                "threshold_violated": threshold,
                                "breach_type": breach_type,
                                "violations_count": self.breach_stats[name]["min"] if breach_type == "low" else
                                self.breach_stats[name]["max"]
                            }
                            prod.send(topic, message)
                            logger.info(f"Notification sent to Kafka topic {topic}")

                        self.history[name] = []
                else:
                    logger.debug(f"No result for query {query}")

            except Exception as e:
                logger.error(f"Error checking SLA for {name}: {e}")

    def start_scheduler(self):
        t_check = self.config.get('settings', {}).get('t_check', 80)
        # Use replace_existing=True to allow updating the job on config change
        self.scheduler.add_job(self.check_sla, 'interval', seconds=t_check, id='sla_job', replace_existing=True)
        if not self.scheduler.running:
            self.scheduler.start()
        logger.info(f"Scheduler started/updated with t_check={t_check}s")

    def update_config(self, new_config):
        t_check = new_config.get('settings', {}).get('t_check', 0)
        t_scrape = self._get_prometheus_scrape_interval()
        
        if t_check < 5 * t_scrape:
             return False, f"Constraint violation: T_check ({t_check}) must be >= 5 * T_scrape ({t_scrape})"

        for metric in new_config.get('metrics', []):
            metric_type = metric.get('type', 'gauge').lower()
            if metric_type != 'gauge':
                return False, f"Invalid metric type: '{metric['name']}' must be type 'gauge', got '{metric_type}'"

        self.config = new_config
        try:
            with open(self.config_path, 'w') as f:
                yaml.dump(self.config, f)
        except Exception as e:
            logger.error(f"Failed to save config: {e}")
            # Non-blocking error for memory update, but good to know
        
        self._initialize_stats()
        self.start_scheduler() # Restarts/updates job
        return True, "Configuration updated"

    def get_config(self):
        return self.config

    def get_stats(self):
        return self.breach_stats

sla_service = SLADetectorService()
