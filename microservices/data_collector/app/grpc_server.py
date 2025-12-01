"""
Defines the gRPC server for the Data Collector microservice.
"""

from concurrent import futures

import grpc
from flask import current_app

try:
    import service_pb2, service_pb2_grpc
    from models import db, UserInterest
except ImportError:
    import service_pb2
    import service_pb2_grpc
    from models import db, UserInterest


class DataCollectorService(service_pb2_grpc.DataCollectorServiceServicer):
    """gRPC service for the Data Collector microservice."""

    def DeleteUserInterests(self, request, context):
        """
        Deletes all interests for a given user.

        Args:
            request (service_pb2.UserRequest): The request containing the user's email.
            context: The gRPC context.

        Returns:
            service_pb2.DeleteInterestsResponse: A response indicating whether the
            deletion was successful and the number of deleted interests.
        """
        with current_app.app_context():
            try:
                num_deleted = (
                    db.session.query(UserInterest)
                    .filter_by(user_email=request.email)
                    .delete()
                )
                db.session.commit()
                print(f"Deleted {num_deleted} interests for user {request.email}")
                return service_pb2.DeleteInterestsResponse(
                    success=True, deleted_count=num_deleted
                )
            except Exception as e:
                db.session.rollback()
                print(f"Error deleting interests for user {request.email}: {e}")
                return service_pb2.DeleteInterestsResponse(
                    success=False, deleted_count=0
                )


def serve_grpc():
    """
    Starts the gRPC server for the Data Collector service.

    The server listens on port 50052 and handles RPCs defined in the DataCollectorService.
    """
    if not service_pb2_grpc:
        print("gRPC modules not found. Run protoc to generate them.")
        return

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    service_pb2_grpc.add_DataCollectorServiceServicer_to_server(
        DataCollectorService(), server
    )
    server.add_insecure_port("[::]:50052")
    print("gRPC Server starting on port 50052...")
    server.start()
    server.wait_for_termination()
