"""
Configuration variables for the Data Collector microservice.
"""

import os

DATABASE_URL: str = os.environ.get("DATABASE_URL")
DATA_COLLECTOR_GRPC_HOST: str = os.environ.get(
    "DATA_COLLECTOR_GRPC_HOST", "data-collector:50052"
)
