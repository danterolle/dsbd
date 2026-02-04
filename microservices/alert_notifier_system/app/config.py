import os

KAFKA_BROKER_URL = os.environ.get("KAFKA_BROKER_URL", "kafka:9092")
CONSUMER_TOPIC = "to-notifier"
SLA_BREACH_TOPIC = "sla_breach"
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
DATABASE_URL = os.environ.get("DATABASE_URL")
