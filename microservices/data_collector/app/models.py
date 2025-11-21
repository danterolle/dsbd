from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import DateTime, String, Integer


class Base(DeclarativeBase):
    pass


db = SQLAlchemy(model_class=Base)


class UserInterest(db.Model):
    __tablename__ = "user_interests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_email: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    airport_code: Mapped[str] = mapped_column(String(4), nullable=False)


# class StateVectors(db.Model):
"""
    Class that represents data of certain flight.
    Commented for future developments.
"""
#     __tablename__ = "state_vectors"

#     id: Mapped[int] = mapped_column(Integer, primary_key=True)
#     icao24: Mapped[str] = mapped_column(String(24), nullable=False)
#     callsign: Mapped[str] = mapped_column(String(20), nullable=True)
#     origin_country: Mapped[str] = mapped_column(String(50), nullable=False)
#     time_position: Mapped[int] = mapped_column(int, nullable=False)
#     last_contact: Mapped[int] = mapped_column(int)
#     longitude: Mapped[float] = mapped_column(Float, nullable=True)
#     latitude: Mapped[float] = mapped_column(Float, nullable=True)
#     geo_altitude: Mapped[float] = mapped_column(Float, nullable=True)
#     on_ground: Mapped[bool] = mapped_column(Boolean, nullable=False)
#     velocity: Mapped[float] = mapped_column(Float, nullable=True)
#     true_track: Mapped[float] = mapped_column(Float, nullable=True)
#     vertical_rate: Mapped[float] = mapped_column(Float, nullable=True)
#     sensors: Mapped[str] = mapped_column(String(100), nullable=True)
#     baro_altitude: Mapped[float] = mapped_column(Float, nullable=True)
#     squawk: Mapped[str] = mapped_column(String(10), nullable=True)
#     spi: Mapped[bool] = mapped_column(Boolean, nullable=False)
#     position_source: Mapped[int] = mapped_column(Integer, nullable=False)
#     category: Mapped[int] = mapped_column(Integer, nullable=True)

#     def __repr__(self):
#         return f"<Flight {self.callsign} at {self.airport_code}>"


class FlightData(db.Model):
    """
    Class that represents data of a certain flight (departure and arrival).
    """

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

    def __repr__(self):
        return f"<Flight {self.callsign} from {self.est_departure_airport} to {self.est_arrival_airport}>"
