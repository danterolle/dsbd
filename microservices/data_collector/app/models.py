"""
Define the database models for the Data Collector microservice.
"""
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import DateTime, String, Integer


class Base(DeclarativeBase):
    """Base class for declarative models."""
    pass


db = SQLAlchemy(model_class=Base)


class UserInterest(db.Model):
    """Represents a user's interest in a specific airport."""
    __tablename__ = "user_interests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_email: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    airport_code: Mapped[str] = mapped_column(String(4), nullable=False)

    def __repr__(self) -> str:
        """Returns a string representation of the UserInterest object."""
        return f"<UserInterest {self.user_email} - {self.airport_code}>"


class FlightData(db.Model):
    """Represents the data for a single flight."""
    __tablename__ = "flight_data"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    icao24: Mapped[str] = mapped_column(String(24), nullable=False)
    first_seen: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    est_departure_airport: Mapped[str] = mapped_column(String(4), nullable=True)
    last_seen: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    est_arrival_airport: Mapped[str] = mapped_column(String(4), nullable=True)
    callsign: Mapped[str] = mapped_column(String(10), nullable=True)
    est_departure_airport_horiz_distance: Mapped[int] = mapped_column(
        Integer, nullable=True
    )
    est_departure_airport_vert_distance: Mapped[int] = mapped_column(
        Integer, nullable=True
    )
    est_arrival_airport_horiz_distance: Mapped[int] = mapped_column(
        Integer, nullable=True
    )
    est_arrival_airport_vert_distance: Mapped[int] = mapped_column(
        Integer, nullable=True
    )
    departure_airport_candidates_count: Mapped[int] = mapped_column(
        Integer, nullable=True
    )
    arrival_airport_candidates_count: Mapped[int] = mapped_column(
        Integer, nullable=True
    )

    def to_dict(self) -> dict:
        """
        Converts the FlightData object to a dictionary.

        Returns:
            dict: A dictionary representation of the flight data.
        """
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}

    def __repr__(self) -> str:
        """Returns a string representation of the FlightData object."""
        return f"<Flight {self.callsign} from {self.est_departure_airport} to {self.est_arrival_airport}>"
