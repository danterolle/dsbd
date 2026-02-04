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