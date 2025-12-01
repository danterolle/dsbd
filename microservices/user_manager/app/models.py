"""This script defines the database models for the User Manager microservice.

It includes the model for users.
"""
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String


class Base(DeclarativeBase):
    """Base class for declarative models."""
    pass


db = SQLAlchemy(model_class=Base)


class User(db.Model):
    """Represents a user of the application."""
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(120), primary_key=True)
    first_name: Mapped[str] = mapped_column(String(50), nullable=False)
    last_name: Mapped[str] = mapped_column(String(50), nullable=False)
    tax_code: Mapped[str] = mapped_column(String(16), unique=True, nullable=True)
    iban: Mapped[str] = mapped_column(String(27), nullable=True)

    def to_dict(self) -> dict:
        """Converts the User object to a dictionary.

        Returns:
            dict: A dictionary representation of the user.
        """
        return {
            "email": self.email,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "tax_code": self.tax_code,
        }

    def __repr__(self) -> str:
        """Returns a string representation of the User object."""
        return f"<User {self.email}>"
