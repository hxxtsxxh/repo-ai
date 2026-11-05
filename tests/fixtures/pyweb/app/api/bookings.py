"""Booking endpoints: search, reserve, cancel."""
from fastapi import APIRouter

from app.billing.charges import charge_card
from app.db.models import Booking

router = APIRouter()


@router.post("/bookings")
def create_booking(user_id: int, flight_id: int, amount_cents: int) -> Booking:
    charge_card(user_id, amount_cents)
    return Booking(id=1, user_id=user_id, flight_id=flight_id)


@router.delete("/bookings/{booking_id}")
def cancel_booking(booking_id: int) -> dict:
    return {"cancelled": booking_id}
