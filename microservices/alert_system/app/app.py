import json
import time
import threading
from flask import Flask, jsonify
from kafka import KafkaConsumer, KafkaProducer
from config import KAFKA_BROKER_URL, CONSUMER_TOPIC, PRODUCER_TOPIC
from metrics import track_requests, metrics_endpoint, track_message_processed

app = Flask(__name__)

@app.route("/metrics")
def metrics():
    return metrics_endpoint()

@app.route("/ping")
@track_requests
def ping():
    return jsonify({"message": "pong"}), 200

def kafka_consumer_loop():
    while True:
        try:
            consumer = KafkaConsumer(
                CONSUMER_TOPIC,
                bootstrap_servers=KAFKA_BROKER_URL,
                value_deserializer=lambda v: json.loads(v.decode("utf-8")),
            )

            producer = KafkaProducer(
                bootstrap_servers=KAFKA_BROKER_URL,
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            )
            print("Alert System connected to Kafka.")
            break
        except Exception as e:
            print(f"Could not connect to Kafka, retrying in 5 seconds... Error: {e}")
            time.sleep(5)

    for message in consumer:
        try:
            data = message.value
            print(f"Received message: {data}")

            flight_count = data.get("flight_count", 0)
            high_value = data.get("high_value")
            low_value = data.get("low_value")
            condition = None

            if high_value is not None and flight_count > high_value:
                condition = f"exceeded the high threshold of {high_value}"
            elif low_value is not None and flight_count < low_value:
                condition = f"is below the low threshold of {low_value}"

            if condition:
                notification = {
                    "user_email": data["user_email"],
                    "airport_code": data["airport_code"],
                    "condition": f"The number of flights ({flight_count}) {condition}.",
                }
                producer.send(PRODUCER_TOPIC, notification)
                print(f"Sent notification to {PRODUCER_TOPIC}: {notification}")
            
            track_message_processed(True)
        except Exception as e:
            print(f"Error processing message: {e}")
            track_message_processed(False)

if __name__ == "__main__":
    # Start Kafka consumer in a background thread
    kafka_thread = threading.Thread(target=kafka_consumer_loop, daemon=True)
    kafka_thread.start()

    # Start Flask app
    app.run(host="0.0.0.0", port=5000)


