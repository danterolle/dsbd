"""This script contains the business logic for the User Manager microservice.

It includes functions for interacting with other microservices via gRPC.
"""
import grpc

from config import DATA_COLLECTOR_GRPC_HOST

try:
    import service_pb2
    import service_pb2_grpc
except ImportError:
    import service_pb2
    import service_pb2_grpc


def get_data_collector_grpc_stub():
    """Creates and returns a gRPC stub for the Data Collector service.

    Returns:
        A gRPC stub for the Data Collector service, or None if the host is not set.
    """
    if not DATA_COLLECTOR_GRPC_HOST:
        return None
    channel = grpc.insecure_channel(DATA_COLLECTOR_GRPC_HOST)
    return service_pb2_grpc.DataCollectorServiceStub(channel)


def delete_user_interests_grpc(email: str) -> None:
    """Deletes user interests via gRPC call to Data Collector service.

    Args:
        email (str): The email of the user whose interests are to be deleted.
    """
    stub = get_data_collector_grpc_stub()
    if not stub:
        print("gRPC stub for data-collector not available.")
        return

    try:
        response = stub.DeleteUserInterests(service_pb2.UserRequest(email=email))
        if response.success:
            print(
                f"Successfully deleted {response.deleted_count} interests for {email}"
            )
        else:
            print(f"Failed to delete interests for {email}")
    except grpc.RpcError as e:
        print(f"gRPC Error calling data-collector: {e}")
