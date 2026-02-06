import asyncio
import json
import threading
import telegram
from flask import Flask, jsonify
from aiokafka import AIOKafkaConsumer
from sqlalchemy import create_engine, Column, String
from sqlalchemy.orm import sessionmaker, declarative_base

from config import (
    KAFKA_BROKER_URL,
    CONSUMER_TOPIC,
    TELEGRAM_BOT_TOKEN,
    DATABASE_URL, SLA_BREACH_TOPIC,
)
from metrics import track_requests, metrics_endpoint, track_notification_sent

Base = declarative_base()

app = Flask(__name__)

@app.route("/metrics")
def metrics():
    return metrics_endpoint()

@app.route("/ping")
@track_requests
def ping():
    return jsonify({"message": "pong"}), 200

def run_flask():
    app.run(host="0.0.0.0", port=5000)

class User(Base):
    __tablename__ = "users"
    email = Column(String, primary_key=True)
    telegram_chat_id = Column(String)


def get_db_session():
    """Creates and returns a new SQLAlchemy session factory."""
    try:
        engine = create_engine(DATABASE_URL)
        Session = sessionmaker(bind=engine)
        print("Database connection successful.")
        return Session
    except Exception as e:
        print(f"Could not connect to database: {e}")
        return None


def get_user_by_email(session, email):
    """Synchronous helper to query user by email."""
    return session.query(User).filter_by(email=email).first()


async def main():
    """
    Main asynchronous routine.
    Connects to Kafka and Telegram, consumes messages, and sends notifications.
    """
    print("Starting Alert Notifier System...")

    SessionFactory = get_db_session()
    if not SessionFactory:
        print("Could not create DB session factory. Exiting.")
        return

    bot = None
    try:
        bot = telegram.Bot(token=TELEGRAM_BOT_TOKEN)
        bot_info = await bot.get_me()
        print(f"Connected to Telegram Bot: {bot_info.first_name}")
    except Exception as e:
        print(f"Warning: Could not connect to Telegram: {e}")

    consumer = AIOKafkaConsumer(
        CONSUMER_TOPIC,
        SLA_BREACH_TOPIC,
        bootstrap_servers=KAFKA_BROKER_URL,
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        group_id="alert_notifier_group",
        auto_offset_reset="earliest",
    )

    while True:
        try:
            print("Attempting to connect to Kafka...")
            await consumer.start()
            print("Connected to Kafka.")
            break
        except Exception as e:
            print(f"Failed to start consumer (Kafka might not be ready): {e}")
            print("Retrying in 5 seconds...")
            await asyncio.sleep(5)

    while True:
        try:
            await consumer._client.force_metadata_update()
            partitions = consumer.partitions_for_topic(CONSUMER_TOPIC)
            sla_partitions = consumer.partitions_for_topic(SLA_BREACH_TOPIC)
            if (partitions is not None and len(partitions) > 0) and \
               (sla_partitions is not None and len(sla_partitions) > 0):
                print(f"Topic '{CONSUMER_TOPIC}' found with partitions: {partitions}")
                print(f"Topic '{SLA_BREACH_TOPIC}' found with partitions: {sla_partitions}")
                break
        except Exception as e:
            print(f"Error checking topic: {e}")

        print(f"Topics '{CONSUMER_TOPIC}' and '{SLA_BREACH_TOPIC}' not found yet. Waiting...")
        await asyncio.sleep(2)

    print("Starting message consumption...")
    try:
        async for message in consumer:
            try:
                data = message.value
                topic = message.topic
                print(f"Received message from {topic}: {data}")

                if topic == SLA_BREACH_TOPIC:
                    # SLA Breach notification is broadcast to a default admin/support email or specific users
                    # For this project, we'll send it to the 'seed user' or a generic admin if available.
                    # As a default, we'll try to find any registered user to notify them of the system status.
                    user_email = "mario.rossi@gmail.com" # Default admin for SLA notifications
                    text_message = (
                        f"🚨 *SLA BREACH DETECTED* 🚨\n\n"
                        f"Metric: *{data.get('metric')}*\n"
                        f"Type: *{data.get('breach_type').upper()}*\n\n"
                        f"Observed: `{data.get('observed_value')}`\n"
                        f"Threshold: `{data.get('threshold_violated')}`\n"
                        f"Violations: {data.get('violations_count')}\n\n"
                        f"Timestamp: _{data.get('timestamp')}_"
                    )
                else:
                    user_email = data.get("user_email")
                    text_message = (
                        f"🔔 *Flight Alert* 🔔\n\n"
                        f"Airport: *{data.get('airport_code')}*\n\n"
                        f"Details: {data.get('condition')}"
                    )

                if not user_email:
                    continue

                loop = asyncio.get_running_loop()
                db_session = SessionFactory()
                try:
                    user = await loop.run_in_executor(
                        None, get_user_by_email, db_session, user_email
                    )

                    if user and user.telegram_chat_id:
                        if bot:
                            try:
                                await bot.send_message(
                                    chat_id=user.telegram_chat_id,
                                    text=text_message,
                                    parse_mode=telegram.constants.ParseMode.MARKDOWN,
                                )
                                print(f"Sent Telegram notification to {user_email} for topic {topic}")
                                track_notification_sent(True)
                            except Exception as e:
                                print(
                                    f"Failed to send Telegram message to {user_email}: {e}"
                                )
                                track_notification_sent(False)
                        else:
                            print(f"Telegram Bot not configured. Cannot send message to {user_email}.")
                            track_notification_sent(False)
                    else:
                        print(
                            f"User {user_email} not found or has no Telegram chat ID."
                        )
                        track_notification_sent(False)
                finally:
                    await loop.run_in_executor(None, db_session.close)
            except Exception as e:
                print(f"Error processing message: {e}")
                track_notification_sent(False)

    finally:
        await consumer.stop()
        print("Kafka consumer stopped.")


async def run_app():
    """Starts the main application and Flask server in a separate thread."""
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    await main()


if __name__ == "__main__":
    asyncio.run(run_app())
