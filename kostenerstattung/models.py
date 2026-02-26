from enum import Enum
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class ErstattungsState(Enum):
    NEW = "neu/unbezahlt"
    PAID = "bezahlt"
    BOOKED = "verbucht (hier im System)"
    DONE = "in Webling verbucht"


class TableErstattung(db.Model):
    __tablename__ = "erstattungen"

    id = db.Column(db.Integer, primary_key=True)
    state = db.Column(db.Enum(ErstattungsState), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.now, nullable=False)

    name = db.Column(db.Text, nullable=False)
    email = db.Column(db.Text, nullable=False)
    name_bank_account = db.Column(db.Text, nullable=False)
    iban = db.Column(db.Text, nullable=False)
    description = db.Column(db.Text, nullable=False)
    betrag = db.Column(db.Float, nullable=False)

    ticket_id = db.Column(db.Integer(), nullable=True)
    ticket_number = db.Column(db.Integer(), nullable=True)

    paid_at = db.Column(db.DateTime(timezone=True), nullable=True)
    verwendungszweck = db.Column(db.Text, nullable=True)

    booked_at = db.Column(db.DateTime(timezone=True), nullable=True)
    kostenart = db.Column(db.Integer, nullable=True)
    buchungsperiode_id = db.Column(db.Integer(), nullable=True)
    kostenstelle_id = db.Column(db.Integer, nullable=True)
    buchungskonto_soll_id = db.Column(db.Integer(), nullable=True)
    buchungskonto_haben_id = db.Column(db.Integer(), nullable=True)
    entrygroup_id = db.Column(db.Integer(), nullable=True)
    buchungs_id = db.Column(db.Integer(), nullable=True)

    def __str__(self):
        return f"Erstattung #{self.id}"
