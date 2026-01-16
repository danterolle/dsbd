import asyncio
import json
import os
import telegram
from aiokafka import AIOKafkaConsumer
from sqlalchemy import create_engine, Column, String
from sqlalchemy.orm import sessionmaker, declarative_base

from config import (
    KAFKA_BROKER_URL,
    CONSUMER_TOPIC,
    TELEGRAM_BOT_TOKEN,
    DATABASE_URL,
)

Base = declarative_base()


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

    try:
        bot = telegram.Bot(token=TELEGRAM_BOT_TOKEN)
        bot_info = await bot.get_me()
        print(f"Connected to Telegram Bot: {bot_info.first_name}")
    except Exception as e:
        print(f"Could not connect to Telegram: {e}. Exiting.")
        return

    consumer = AIOKafkaConsumer(
        CONSUMER_TOPIC,
        bootstrap_servers=KAFKA_BROKER_URL,
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        group_id="alert_notifier_group",
        auto_offset_reset="earliest",
    )

    # Robust startup loop
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

    # Wait for Topic to be created
    while True:
        try:
            # Refresh metadata to discover new topics
            await consumer._client.force_metadata_update()
            partitions = consumer.partitions_for_topic(CONSUMER_TOPIC)
            if partitions is not None and len(partitions) > 0:
                print(f"Topic '{CONSUMER_TOPIC}' found with partitions: {partitions}")
                break
        except Exception as e:
            print(f"Error checking topic: {e}")

        print(f"Topic '{CONSUMER_TOPIC}' not found yet. Waiting...")
        await asyncio.sleep(2)

    print("Starting message consumption...")
    try:
        async for message in consumer:
            try:
                data = message.value
                print(f"Received notification: {data}")

                user_email = data.get("user_email")
                if not user_email:
                    continue

                loop = asyncio.get_running_loop()
                db_session = SessionFactory()
                try:
                    user = await loop.run_in_executor(
                        None, get_user_by_email, db_session, user_email
                    )

                    if user and user.telegram_chat_id:
                        try:
                            text_message = (
                                f"🔔 *Flight Alert* 🔔\n\n"
                                f"Airport: *{data.get('airport_code')}*\n\n"
                                f"Details: {data.get('condition')}"
                            )
                            await bot.send_message(
                                chat_id=user.telegram_chat_id,
                                text=text_message,
                                parse_mode=telegram.constants.ParseMode.MARKDOWN,
                            )
                            print(f"Sent Telegram notification to {user_email}")
                        except Exception as e:
                            print(
                                f"Failed to send Telegram message to {user_email}: {e}"
                            )
                    else:
                        print(
                            f"User {user_email} not found or has no Telegram chat ID."
                        )
                finally:
                    await loop.run_in_executor(None, db_session.close)
            except Exception as e:
                print(f"Error processing message: {e}")

    finally:
        await consumer.stop()
        print("Kafka consumer stopped.")


async def run_app():
    """Waits for Kafka to be ready and then runs the main application."""

    print("Waiting for 20 seconds to ensure Kafka is ready...")

    await asyncio.sleep(20)

    await main()


if __name__ == "__main__":

    asyncio.run(run_app())
