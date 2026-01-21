"""
Prometheus configuration for the Alert Notifier System microservice.
"""

import os
import time
from functools import wraps
from flask import request
from prometheus_client import Counter, Gauge, generate_latest, CONTENT_TYPE_LATEST

NODE_NAME = os.environ.get("NODE_NAME", os.environ.get("HOSTNAME", "unknown"))
SERVICE_NAME = "alert_notifier_system"

# COUNTER: Total number of HTTP requests received
http_requests_total = Counter(
    "http_requests_total",
    "Total number of HTTP requests received",
    ["service", "node", "method", "endpoint", "status"]
)

# GAUGE: Response time of the last request (in seconds)
http_request_duration_seconds = Gauge(
    "http_request_duration_seconds",
    "HTTP request duration (in seconds)",
    ["service", "node", "method", "endpoint"]
)

# GAUGE: Number of active requests
http_requests_in_progress = Gauge(
    "http_requests_in_progress",
    "Number of HTTP requests currently being processed",
    ["service", "node"]
)

# Custom metric for Alert Notifier System: Notifications sent
notifications_sent_total = Counter(
    "notifications_sent_total",
    "Total number of notifications sent by alert_notifier_system",
    ["service", "node", "status"]
)

def track_requests(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        http_requests_in_progress.labels(
            service=SERVICE_NAME,
            node=NODE_NAME
        ).inc()

        start_time = time.time()
        status_code = 500

        try:
            response = func(*args, **kwargs)
            if isinstance(response, tuple):
                status_code = response[1]
            else:
                status_code = response.status_code if hasattr(response, 'status_code') else 200
            return response
        except Exception:
            status_code = 500
            raise
        finally:
            duration = time.time() - start_time
            endpoint = request.endpoint or request.path

            http_requests_total.labels(
                service=SERVICE_NAME,
                node=NODE_NAME,
                method=request.method,
                endpoint=endpoint,
                status=str(status_code)
            ).inc()

            http_request_duration_seconds.labels(
                service=SERVICE_NAME,
                node=NODE_NAME,
                method=request.method,
                endpoint=endpoint
            ).set(duration)

            http_requests_in_progress.labels(
                service=SERVICE_NAME,
                node=NODE_NAME
            ).dec()

    return wrapper

def track_notification_sent(success: bool):
    notifications_sent_total.labels(
        service=SERVICE_NAME,
        node=NODE_NAME,
        status="success" if success else "failure"
    ).inc()

def metrics_endpoint():
    return generate_latest(), 200, {"Content-Type": CONTENT_TYPE_LATEST}
