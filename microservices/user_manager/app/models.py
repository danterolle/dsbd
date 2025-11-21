from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Integer, Float, Boolean, DateTime, ForeignKey
from datetime import datetime


class Base(DeclarativeBase):
    pass


db = SQLAlchemy(model_class=Base)


class User(db.Model):
    """
    Class that represents a user in the system.
    """

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(120), primary_key=True)
    nome: Mapped[str] = mapped_column(String(50), nullable=False)
    cognome: Mapped[str] = mapped_column(String(50), nullable=False)
    codice_fiscale: Mapped[str] = mapped_column(String(16), unique=True, nullable=True)
    iban: Mapped[str] = mapped_column(String(27), nullable=True)

    def to_dict(self):
        return {
            "email": self.email,
            "nome": self.nome,
            "cognome": self.cognome,
            "codice_fiscale": self.codice_fiscale,
        }
