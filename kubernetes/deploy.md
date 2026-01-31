# Flight Tracker Kubernetes Deployment Guide

This directory contains the necessary Kubernetes manifests and a helper script to deploy the Flight Tracker microservices architecture locally using [kind](https://kind.sigs.k8s.io/).

## 1. Prerequisites

Ensure you have the following installed:
- **Docker**: Container runtime.
- **kind**: Tool for running local Kubernetes clusters.
- **kubectl**: Kubernetes command-line tool.
- **curl/Postman**: For testing API endpoints.

## 2. Deployment Script (`deploy.sh`)

The `deploy.sh` script automates the entire lifecycle of the deployment.

**Note on Cluster Topology:**
By default, the script creates a **Single-Node Cluster** (Control Plane + Worker in one) to save resources. 
If you wish to simulate a **Multi-Node Cluster** (1 Control Plane + 2 Workers), open `kubernetes/deploy.sh` and uncomment the worker lines at the bottom of the Kind configuration section before running the script.

### Usage

```bash
Usage: ./kubernetes/deploy.sh [ACTION] [OPTIONS]

Actions:
  up (default)    Create cluster, build images, and deploy.
  down            Delete the kind cluster.
  stop-pf         Stop all active port-forwarding processes.

Options for 'up':
  --pf, --port-forward    Automatically start port-forwarding after deployment.
  --ingress               Install NGINX Ingress Controller and enable Ingress access.
```

### Key Features
- **Automatic Setup**: Creates a `kind` cluster named `flight-tracker` with necessary port mappings.
- **Image Building**: Builds Docker images for all microservices from the local source.
- **Wait Logic**: Waits for all pods and deployments (including Kafka, Zookeeper, Databases) to be fully ready.
- **Database Seeding**: Automatically runs `seed.sh` to populate the database with test users and interests.
- **Logging**: Deployment logs are saved to the `logs/` directory with a timestamp (e.g., `logs/flight-tracker-20260125-225406.log`).
- **Cleanup**: The `down` action fully removes the cluster, and `stop-pf` kills background port-forwarding processes started by the script.

## 3. Accessing Services

The services are accessible via multiple methods.

### Method A: NodePorts (Standard)
The cluster is configured to map these ports directly to your localhost (via `extraPortMappings` in `kind` config).

| Service            | Local URL                |
|:-------------------|:-------------------------|
| **User Manager**   | `http://localhost:30000` |
| **Data Collector** | `http://localhost:30001` |
| **Alert System**   | `http://localhost:30002` |
| **Alert Notifier** | `http://localhost:30003` |
| **Prometheus**     | `http://localhost:30090` |

### Method B: Port-Forwarding (with `--pf`)
If you run with `--pf`, the script creates background `kubectl port-forward` processes:

| Service            | Local URL               |
|:-------------------|:------------------------|
| **User Manager**   | `http://localhost:5000` |
| **Data Collector** | `http://localhost:5001` |
| **Alert System**   | `http://localhost:5002` |
| **Alert Notifier** | `http://localhost:5003` |

### Method C: Ingress (with `--ingress`)
If installed, services are routed via an NGINX Ingress Controller on port 80:

| Service            | Ingress Prefix    | Example URL                            |
|:-------------------|:------------------|:---------------------------------------|
| **User Manager**   | `/user-manager`   | `http://localhost/user-manager/ping`   |
| **Data Collector** | `/data-collector` | `http://localhost/data-collector/ping` |

## 4. Automatic Database Seeding

The `deploy.sh` script runs `seed.sh` at the end of the deployment. This creates the following test data:

**Users:**
- `mario.rossi@gmail.com`
- `mario.verdi@gmail.com`
- `enzo.bianchi@gmail.com`
- `neri.parenti@gmail.com`
- `luca.blu@gmail.com`

**Interests:**
- Mario Rossi tracks `LIRF` and `LICC`.
- Mario Verdi tracks `LICC` and `LIMC`.
- Others track various airports (`KJFK`, `EGLL`, `RJTT`).

## 5. API Documentation & Examples

These examples use the **NodePorts (Method A)**.

### User Manager (Port 30000)

| Action       | Command Example                                                                                                                                                                          |
|:-------------|:-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **Add User** | `curl -X POST http://localhost:30000/users -H "Content-Type: application/json" -H "Idempotency-Key: key1" -d '{"email": "test@example.com", "first_name": "Test", "last_name": "User"}'` |
| **Ping**     | `curl http://localhost:30000/ping`                                                                                                                                                       |
| **Metrics**  | `curl http://localhost:30000/metrics`                                                                                                                                                    |

### Data Collector (Port 30001)

| Action           | Command Example                                                                                                                                     |
|:-----------------|:----------------------------------------------------------------------------------------------------------------------------------------------------|
| **Add Interest** | `curl -X POST http://localhost:30001/interests -H "Content-Type: application/json" -d '{"email": "mario.rossi@gmail.com", "airport_code": "LIRF"}'` |
| **Get Flights**  | `curl http://localhost:30001/flights/LIRF`                                                                                                          |
| **Ping**         | `curl http://localhost:30001/ping`                                                                                                                  |

### Internal Systems (30002 & 30003)

| Service            | Ping Command                       |
|:-------------------|:-----------------------------------|
| **Alert System**   | `curl http://localhost:30002/ping` |
| **Alert Notifier** | `curl http://localhost:30003/ping` |

## 6. Monitoring (Prometheus)

Access the Prometheus UI at: [http://localhost:30090](http://localhost:30090)

## 6. Configuration & Credentials

### API Keys
The system requires valid credentials for external services. You have two options:
1.  **Create your own**: 
    *   **Telegram**: Use [BotFather](https://t.me/botfather) to create a bot and get a token.
    *   **OpenSky**: Register for a free account at [OpenSky Network](https://opensky-network.org/).
2.  **Request from authors**: You can contact the authors (Dario or Matteo) to receive testing credentials.

Update the `opensky-secrets` and `telegram-secrets` sections in `kubernetes/secrets.yaml` with your keys.

### Infrastructure
The deployment includes:
- **PostgreSQL**: Two instances (User DB, Data DB).
- **Kafka & Zookeeper**: For asynchronous messaging.
- **Prometheus**: For metrics collection.

---

## 7. End-to-End Test: Triggering an Alert

## 7. End-to-End Test: Triggering an Alert

To verify the full pipeline (User -> Interest -> Flight Check -> Alert -> Notification):

### Step 1: Get your Telegram Chat ID
1.  Open Telegram and find a bot like `@userinfobot`.
2.  Send `/start` to get your numeric ID.

### Step 2: Register Chat ID
Associate your Telegram ID with a seeded user (e.g., Mario Rossi):
```bash
curl -X POST http://localhost:30000/users/telegram \
  -H "Content-Type: application/json" \
  -d '{
    "email": "mario.rossi@gmail.com",
    "telegram_chat_id": "YOUR_CHAT_ID"
  }'
```

### Step 3: Add a Triggering Interest
Add an interest with a **high_value of 0**. Since there is likely at least 1 flight (or none, if it's night), setting `low_value` to -1 guarantees a trigger if any flights are found (or we can tweak logic). A safer bet is setting `high_value` to `0` so if *any* flight is found, it alerts. If no flights are found, it won't alert unless we set `low_value`.

```bash
curl -X POST http://localhost:30001/interests \
  -H "Content-Type: application/json" \
  -d '{
    "email": "mario.rossi@gmail.com",
    "airport_code": "LIRF",
    "high_value": 0,
    "low_value": -1
  }'
```

### Step 4: Interact with Bot
Start a chat with **@sky_dsbd_bot** on Telegram so it can message you.

### Step 5: Wait
The system checks flights periodically (configured interval). When the condition is met, you should receive a Telegram message.

## 8. Troubleshooting

**View Logs:**
```bash
# Check alert system logs
kubectl logs -l app=alert-system --tail=100 -f

# Check kafka logs
kubectl logs -l app=kafka --tail=50
```

**Restart Port Forwarding:**
If ports are occupied or failed:
```bash
./kubernetes/deploy.sh stop-pf
./kubernetes/deploy.sh up --pf
```

**Full Reset:**
```bash
./kubernetes/deploy.sh down
./kubernetes/deploy.sh up
```