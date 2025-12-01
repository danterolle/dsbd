"""This script contains the gRPC server for the User Manager microservice.

It defines the gRPC service for the user manager, which handles RPCs for
checking if a user exists.
"""

from concurrent import futures

import grpc
from flask import current_app

try:
    import service_pb2, service_pb2_grpc
    from models import db, User
except ImportError:
    import service_pb2
    import service_pb2_grpc
    from models import db, User


class UserService(service_pb2_grpc.UserServiceServicer):
    """gRPC service for the User Manager microservice."""

    def CheckUserExists(self, request, context):
        """
        Checks if a user exists in the database.

        Args:
            request (service_pb2.UserRequest): The request containing the user's email.
            context: The gRPC context.

        Returns:
            service_pb2.UserResponse: A response indicating whether the user exists.
        """
        with current_app.app_context():
            try:
                user = db.session.get(User, request.email)
                exists = user is not None
                return service_pb2.UserResponse(exists=exists)
            except Exception as e:
                print(f"Error checking user existence: {e}")
                return service_pb2.UserResponse(exists=False)


def serve_grpc():
    """
    Starts the gRPC server for the User Manager service.

    The server listens on port 50051 and handles RPCs defined in the
    UserService.
    """
    if not service_pb2_grpc:
        print("gRPC modules not found. Run protoc to generate them.")
        return

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    service_pb2_grpc.add_UserServiceServicer_to_server(UserService(), server)
    server.add_insecure_port("[::]:50051")
    print("gRPC Server starting on port 50051...")
    server.start()
    server.wait_for_termination()
