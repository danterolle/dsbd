import uuid
import random
from locust import HttpUser, task, between

# Test Data Configuration
AIRPORTS = ["LICC", "LIRF", "LIMC", "KJFK", "EGLL", "RJTT", "EDDF", "LFPG", "OMDB"]
SEED_USER = "mario.rossi@gmail.com"


class FlightTrackerLoadTester(HttpUser):
    """
    Main Load Tester class for the Flight Tracker System.
    This class simulates virtual users interacting with the microservices architecture
    deployed on Kubernetes. It covers both standard operational flows and stress scenarios.
    """

    wait_time = between(1, 5)

    def on_start(self):
        """
        Setup routine executed when a virtual user is instantiated.
        Generates a unique email and idempotency key for the session.
        """
        self.user_email = f"test_{uuid.uuid4().hex[:8]}@example.com"
        self.idempotency_key = str(uuid.uuid4())

    @task(1)
    def health_check_all(self):
        """
        Task: System Health Verification.
        Pings all exposed microservices (ports 30000-30003) to ensure they are reachable.
        Uses catch_response to manually handle and log failures in the statistics.
        """
        services = [30000, 30001, 30002, 30003, 30004]
        for port in services:
            with self.client.get(
                f"http://127.0.0.1:{port}/ping",
                name=f"Ping Port {port}",
                catch_response=True,
            ) as response:
                if response.status_code != 200:
                    response.failure(f"Service on port {port} is down")

    @task(5)
    def user_manager_lifecycle(self):
        """
        Task: User Management Lifecycle (Port 30000).
        Simulates a standard user journey:
        1. Create a new user account with a unique Idempotency-Key.
        2. Retrieve the created user's profile information.
        3. Update the user's Telegram Chat ID for notifications.
        """
        payload = {
            "email": self.user_email,
            "first_name": "Locust",
            "last_name": "User",
        }
        headers = {"Idempotency-Key": self.idempotency_key}

        self.client.post(
            "http://127.0.0.1:30000/users",
            json=payload,
            headers=headers,
            name="UM: Create User",
        )

        self.client.get(
            f"http://127.0.0.1:30000/users/{self.user_email}",
            name="UM: Get User Profile",
        )

        self.client.post(
            "http://127.0.0.1:30000/users/telegram",
            json={
                "email": self.user_email,
                "telegram_chat_id": str(random.randint(100000, 999999)),
            },
            name="UM: Update Telegram ID",
        )

    @task(10)
    def data_collector_read_ops(self):
        """
        Task: Flight Data Exploration (Port 30001).
        Performs frequent read-only operations on the Data Collector:
        - Lists all flights for a random airport.
        - Filters flights by arrival type.
        - Requests calculated daily averages and the last recorded flight.
        This task has a higher weight (10) to simulate heavy user traffic.
        """
        airport = random.choice(AIRPORTS)

        self.client.get(
            f"http://127.0.0.1:30001/flights/{airport}", name="DC: Get Flights"
        )
        self.client.get(
            f"http://127.0.0.1:30001/flights/{airport}?type=arrivals",
            name="DC: Get Arrivals",
        )
        self.client.get(
            f"http://127.0.0.1:30001/flights/average/{airport}", name="DC: Get Average"
        )
        self.client.get(
            f"http://127.0.0.1:30001/flights/last/{airport}", name="DC: Get Last Flight"
        )

    @task(3)
    def trigger_alert_logic(self):
        """
        Task: Notification Pipeline Trigger (Port 30001).
        Adds an airport interest for the seed user. This action triggers the Data Collector
        to produce messages to the 'to-alert-system' Kafka topic, initiating the
        asynchronous alert evaluation flow.
        """
        airport = random.choice(AIRPORTS)
        payload = {
            "email": SEED_USER,
            "airport_code": airport,
            "high_value": random.randint(10, 50),
            "low_value": random.randint(0, 5),
        }
        self.client.post(
            "http://127.0.0.1:30001/interests",
            json=payload,
            name="DC: Add/Update Interest",
        )

    @task(2)
    def test_idempotency_collision(self):
        """
        Task: Idempotency Verification.
        Deliberately sends multiple requests with the exact same Idempotency-Key
        to verify that the User Manager service returns cached responses and prevents
        duplicate database entries (At-Most-Once semantics).
        """
        payload = {
            "email": "duplicate@test.com",
            "first_name": "Dup",
            "last_name": "User",
        }
        headers = {"Idempotency-Key": "fixed-test-key-123"}

        self.client.post(
            "http://127.0.0.1:30000/users",
            json=payload,
            headers=headers,
            name="UM: Idempotency Test",
        )

    @task(4)
    def kafka_stress_test(self):
        """
        STRESS TEST 1: Kafka Producer Hammering.
        Rapidly creates multiple interest entries for the seed user.
        This focuses on saturating the Data Collector's internal producer threads and
        filling the Kafka topics to monitor consumer group performance and potential lag.
        """
        for _ in range(5):
            airport = random.choice(AIRPORTS)
            payload = {
                "email": SEED_USER,
                "airport_code": airport,
                "high_value": 100,
                "low_value": 0,
            }
            self.client.post(
                "http://127.0.0.1:30001/interests",
                json=payload,
                name="STRESS: Kafka Producer Flood",
            )

    @task(4)
    def db_heavy_query_stress(self):
        """
        STRESS TEST 2: Database Heavy Aggregation.
        Targets busy airport hubs to execute computationally expensive SQL queries:
        - Calculating daily averages (requires scanning large datasets and date functions).
        - Bulk fetching flight lists (requires high memory allocation and JSON serialization).
        This test is designed to verify the stability of the Data Collector under DB pressure.
        """
        busy_airports = ["LIRF", "KJFK", "EGLL", "LFPG"]
        target = random.choice(busy_airports)

        self.client.get(
            f"http://127.0.0.1:30001/flights/average/{target}",
            name="STRESS: DB Heavy Avg Calculation",
        )

        self.client.get(
            f"http://127.0.0.1:30001/flights/{target}", name="STRESS: DB Bulk Fetch"
        )

    @task(2)
    def sla_detector_health(self):
        """
        Task: SLA Breach Detector Health Check.
        Verifies the SLA Breach Detector service is running and responsive.
        """
        self.client.get(
            "http://127.0.0.1:30004/ping",
            name="SLA: Ping",
        )
        self.client.get(
            "http://127.0.0.1:30004/health",
            name="SLA: Health Check",
        )

    @task(3)
    def sla_detector_read_config(self):
        """
        Task: Read SLA Configuration.
        Fetches the current SLA configuration including monitored metrics and thresholds.
        """
        self.client.get(
            "http://127.0.0.1:30004/sla/config",
            name="SLA: Get Config",
        )

    @task(3)
    def sla_detector_breach_stats(self):
        """
        Task: Read Breach Statistics.
        Fetches the current breach statistics showing which metrics have violated
        their SLA thresholds and how many times since the service startup.
        """
        self.client.get(
            "http://127.0.0.1:30004/breach/stats",
            name="SLA: Get Breach Stats",
        )

    @task(1)
    def sla_detector_metrics(self):
        """
        Task: Prometheus Metrics Endpoint.
        Verifies the /metrics endpoint is available for Prometheus scraping.
        """
        self.client.get(
            "http://127.0.0.1:30004/metrics",
            name="SLA: Prometheus Metrics",
        )
