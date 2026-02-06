from prometheus_client import Counter

SERVICE_NAME = "sla_breach_detector"

sla_checks_total = Counter(
    "sla_checks_total", 
    "Total SLA check cycles", 
    ["service"]
)

sla_breaches_total = Counter(
    "sla_breaches_total", 
    "Total breaches detected", 
    ["service", "metric_name", "breach_type"]
)
