# Distributed Systems and Big Data (DSBD) Project

This project is a distributed system designed to manage user information, collect flight data from the OpenSky Network, provide real-time, threshold-based alerts via Telegram, monitor SLA compliance, and is deployed on Kubernetes with Prometheus monitoring.

> Note: the microservice `sla_breach_detector` and all its other implementations were written exclusively by Dario Camonita as required to satisfy the requirements of the comprehensive exam.

**Students:**
- Dario Camonita
- Matteo Jacopo Schembri

## Project Structure & History

The `main` branch contains the **final version** of the project (aligned with Homework 3). Previous development stages and homework requirements are preserved in their respective branches:
- **`hw1`**: Initial microservices setup and basic communication.
- **`hw2`**: Integration of Kafka, gRPC, and initial Kubernetes deployment.
- **`hw3`**: Final architecture with Prometheus monitoring, Mock data generation, and full Kubernetes orchestration.

The assignment specifications and deliverables for each phase are available in the respective PDF files: **`hw1.pdf`**, **`hw2.pdf`**, and **`hw3.pdf`**.

## Project Status

This project implements a comprehensive microservices architecture with advanced features like an API Gateway, asynchronous messaging, Circuit Breaker, and integrated monitoring. It includes a **Mock Data Generator** for offline testing, an **Alert Notifier** that integrates with Telegram, and **Load Testing validation via Locust**.

## Architecture

![Architectural Diagram](img/hw2_architecture.png)

The system's architecture is built around several decoupled microservices orchestrated on Kubernetes. An **NGINX API Gateway** provides a single, secure entry point, routing requests to the appropriate services. Asynchronous communication is handled by **Apache Kafka**, which connects data producers (like the `data-collector`) to consumers (like the `alert-system` and `alert-notifier-system`). The `data-collector` integrates a **Circuit Breaker** for resilience against external API failures. The entire system is monitored using **Prometheus**, collecting custom metrics from the microservices.

## Documentation

*   **[Deployment Guide](kubernetes/deploy.md)**: Detailed instructions on how to set up the cluster, deploy services, and run end-to-end tests.
*   **[Technical Documentation](doc.md)**: In-depth explanation of the architecture, API endpoints, and design choices.

## Coding Standards

The Python code in this project adheres to the **PEP 8** style guide. All docstrings for modules, classes, and functions are written to comply with the **PEP 257** standard.

## Quick Start

1.  **Configure Environment**:
    Update `kubernetes/secrets.yaml` with your API keys (OpenSky, Telegram) and database credentials.

2.  **Deploy**:
    Run the helper script to create the local cluster and deploy all services:
    ```bash
    ./kubernetes/deploy.sh
    ```

3.  **Test**:
    The system uses **NodePorts** by default, making services accessible at:
    *   **User Manager**: `http://localhost:30000`
    *   **Data Collector**: `http://localhost:30001`
    *   **SLA Breach Detector**: `http://localhost:30004`
    *   **Prometheus**: `http://localhost:30090`

    For a full End-to-End test guide (including triggering Telegram alerts), please refer to the **[Deployment Guide](kubernetes/deploy.md)**.

4.  **Load Test (Optional)**:
    Run Locust to stress-test the architecture:
    ```bash
    locust
    ```
    Access the dashboard at `http://localhost:8089`.

## Postman Collection

A Postman collection named `DSBD.postman_collection.json` is available for easy API testing.

## OpenSky API

- **Documentation**: https://openskynetwork.github.io/opensky-api/rest.html
- **Limitations**: https://openskynetwork.github.io/opensky-api/rest.html#limitations
