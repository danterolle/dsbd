# Distributed Systems and Big Data (DSBD) Project

This project is a distributed system designed to manage user information, collect flight data from the OpenSky Network, provide real-time, threshold-based alerts via Telegram, and is deployed on Kubernetes with Prometheus monitoring.

**Students:**
- Dario Camonita
- Matteo Jacopo Schembri

## Project Status

This project implements a comprehensive microservices architecture with advanced features like an API Gateway, asynchronous messaging, Circuit Breaker, and integrated monitoring. It is designed for deployment on Kubernetes and includes a full setup script.

## Architecture

![Architectural Diagram](diagrams/final_architecture.png)

The system's architecture is built around several decoupled microservices orchestrated on Kubernetes. An **NGINX API Gateway** provides a single, secure entry point, routing requests to the appropriate services. Asynchronous communication is handled by **Apache Kafka**, which connects data producers (like the `data-collector`) to consumers (like the `alert-system` and `alert-notifier-system`). The `data-collector` integrates a **Circuit Breaker** for resilience against external API failures. The entire system is monitored using **Prometheus**, collecting custom metrics from the microservices.

## Documentation

- Detailed technical documentation, including architectural choices, API endpoints, monitoring details, and Kubernetes manifests explanation, is available in `doc.md`.

## Coding Standards

The Python code in this project adheres to the **PEP 8** style guide. All docstrings for modules, classes, and functions are written to comply with the **PEP 257** standard.

## Setup and Deployment on Kubernetes

This project is designed for deployment on a Kubernetes cluster, with local development facilitated by `kind` (Kubernetes in Docker).

### Prerequisites

- Docker
- kind
- kubectl
- OpenSSL (for generating self-signed SSL certificates)

### Configuration

Modify the `.env` file in the project's root directory to provide necessary credentials and configurations. This file is used during the Docker image build process for some environment variables.

```
# OpenSky Network API Credentials
OPEN_SKY_CLIENT_ID=your_api_client_id
OPEN_SKY_CLIENT_SECRET=your_api_client_secret

# Telegram Bot Token (from BotFather)
TELEGRAM_BOT_TOKEN=your_telegram_bot_token

# Dummy values for database credentials (used in Kubernetes Secrets)
USER_DB_USER=admin
USER_DB_PASSWORD=admin
USER_DB_NAME=user_manager_db
DATA_DB_USER=admin
DATA_DB_PASSWORD=admin
DATA_DB_NAME=data_collector_db
```

### SSL Certificate Generation

For HTTPS access via the API Gateway, a self-signed SSL certificate is required. Run the following command from the project's root directory:

```bash
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout nginx/ssl/nginx-selfsigned.key \
  -out nginx/ssl/nginx-selfsigned.crt \
  -subj "/C=IT/ST=Italy/L=CT/O=Uni/OU=Dev/CN=localhost"
```
This will create the necessary `.key` and `.crt` files inside the `nginx/ssl/` directory. These files are excluded from Git via `.gitignore`.

### Kubernetes Deployment

A script `setup_cluster.sh` is provided to automate the setup of a local Kind cluster and the deployment of all microservices, Kafka, Prometheus, and Ingress.

1.  **Ensure `setup_cluster.sh` is executable:**
    ```bash
    chmod +x setup_cluster.sh
    ```

2.  **Update `kubernetes/secrets.yaml`:**
    Open `kubernetes/secrets.yaml` and replace the placeholder values with your actual credentials from your `.env` file. These secrets are used by Kubernetes deployments.

3.  **Run the setup script:**
    ```bash
    ./setup_cluster.sh
    ```
    This script will:
    *   Create a Kind cluster named `dsbd-cluster` (if it doesn't exist).
    *   Build Docker images for all microservices.
    *   Load these images into the Kind cluster.
    *   Install the NGINX Ingress Controller.
    *   Apply all Kubernetes manifests for databases, Kafka, Zookeeper, microservices, Prometheus, and Ingress.

## Testing the Application

Once the deployment is complete (verify all pods are `Running` with `kubectl get pods`), you can test the application.

### Accessing Services

Services are accessible through the Kubernetes Ingress via `http://localhost/` or `https://localhost/`. HTTP traffic on port 80 will be redirected to HTTPS. Since a self-signed certificate is used, you may need to accept browser security warnings or use `curl -k`.

**Example Ping Endpoints:**
```bash
curl -k https://localhost/user-manager/ping
curl -k https://localhost/data-collector/ping
```

### Full Workflow Test (Telegram Notifications)

1.  **Create User:**
    ```bash
    curl -k -X POST https://localhost/user-manager/users \
    -H "Content-Type: application/json" \
    -H "Idempotency-Key: $(uuidgen)" \
    -d '{"email": "mario.rossi@gmail.com", "first_name": "Mario", "last_name": "Rossi"}'
    ```

2.  **Register Telegram Chat ID:** (Obtain your numeric Chat ID from Telegram's `@userinfobot`)
    ```bash
    curl -k -X POST https://localhost/user-manager/users/telegram \
    -H "Content-Type: application/json" \
    -d '{"email": "mario.rossi@gmail.com", "telegram_chat_id": "YOUR_NUMERIC_CHAT_ID"}'
    ```

3.  **Add Interest with Thresholds:** (This will trigger data fetch and notification if thresholds are met)
    ```bash
    curl -k -X POST https://localhost/data-collector/interests \
    -H "Content-Type: application/json" \
    -H "Idempotency-Key: $(uuidgen)" \
    -d '{
        "email": "mario.rossi@gmail.com",
        "airport_code": "LICC",
        "high_value": 2,
        "low_value": 1
    }'
    ```
    Wait 15-30 seconds, then check your Telegram for the notification.

## Postman Collection

A Postman collection named `DSBD.postman_collection.json` is available for easy API testing. Import it and set the base URL to `https://localhost`.

## OpenSky API

- **Documentation**: https://openskynetwork.github.io/opensky-api/rest.html
- **Limitations**: https://openskynetwork.github.io/opensky-api/rest.html#limitations
