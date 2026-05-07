"""Slack bot for RideSwift notifications."""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, UTC

import httpx
from kafka import KafkaConsumer
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_APP_TOKEN = os.getenv("SLACK_APP_TOKEN")
BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8000")
BACKEND_API_TOKEN = os.getenv("BACKEND_API_TOKEN")

app: App | None = None
if SLACK_BOT_TOKEN:
    app = App(token=SLACK_BOT_TOKEN)


def _backend_headers() -> dict[str, str]:
    """Build backend headers for service requests."""
    if BACKEND_API_TOKEN:
        return {"Authorization": f"Bearer {BACKEND_API_TOKEN}"}
    return {}


def _fetch_booking(booking_id: str) -> dict:
    """Fetch booking details from backend API."""
    response = httpx.get(
        f"{BACKEND_URL}/api/bookings/{booking_id}",
        headers=_backend_headers(),
        timeout=20.0,
    )
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else {}


def _fleet_status_counts() -> tuple[int, int, int]:
    """Return count of available, rented, and maintenance vehicles."""
    response = httpx.get(
        f"{BACKEND_URL}/api/vehicles",
        headers=_backend_headers(),
        timeout=20.0,
    )
    response.raise_for_status()
    vehicles = response.json()
    if not isinstance(vehicles, list):
        return (0, 0, 0)
    available = sum(1 for v in vehicles if v.get("status") == "available")
    rented = sum(1 for v in vehicles if v.get("status") == "rented")
    maintenance = sum(1 for v in vehicles if v.get("status") == "maintenance")
    return (available, rented, maintenance)

# ── Auto-alert managers when a booking is created ─────────────────
def kafka_listener():
    consumer = KafkaConsumer(
        "booking.created",
        bootstrap_servers="kafka:9092",
        value_deserializer=lambda v: json.loads(v.decode())
    )
    for msg in consumer:
        booking = msg.value
        if app is None:
            continue
        app.client.chat_postMessage(
            channel="#pickup-managers",
            blocks=[
                {"type": "section", "text": {"type": "mrkdwn",
                 "text": f"*New Booking Alert* 🚗\n"
                         f"Booking ID: `{booking['booking_id']}`\n"
                         f"Pickup: {booking['pickup_date']}"}},
                {"type": "actions", "elements": [
                    {"type": "button", "text": {"type": "plain_text", "text": "Confirm"},
                     "style": "primary", "value": booking["booking_id"],
                     "action_id": "confirm_booking"},
                    {"type": "button", "text": {"type": "plain_text", "text": "Reject"},
                     "style": "danger", "value": booking["booking_id"],
                     "action_id": "reject_booking"}
                ]}
            ]
        )

threading.Thread(target=kafka_listener, daemon=True).start()

# ── Insurance query via /insurance slash command ───────────────────
if app is not None:
    @app.command("/insurance")
    def handle_insurance_query(ack, body, respond):
        ack()
        question = body["text"]
        customer_id = body.get("channel_id")  # map to actual customer in production

        respond("Checking insurance coverage... ⏳")
        result = httpx.post(
            f"http://rag-service:8002/rag/query/{customer_id}",
            json={"question": question}
        ).json()

        respond(f"*Coverage Answer:*\n{result['answer']}\n\n"
                f"_Source: {result['sources'][0][:100]}..._")

# ── Button handlers ────────────────────────────────────────────────
    @app.action("confirm_booking")
    def confirm(ack, body, client):
        ack()
        booking_id = body["actions"][0]["value"]
        httpx.patch(
            f"{BACKEND_URL}/api/bookings/{booking_id}",
            json={"status": "confirmed"},
            headers=_backend_headers(),
            timeout=20.0,
        )
        client.chat_update(channel=body["channel"]["id"],
                           ts=body["message"]["ts"],
                           text=f"✅ Booking `{booking_id}` confirmed!")

    @app.command("/return")
    def return_booking(ack, body, respond):
        """Handle /return <booking_id> to request return confirmation."""
        ack()
        booking_id = body.get("text", "").strip()
        if not booking_id:
            respond("Usage: `/return <booking_id>`")
            return

        try:
            booking = _fetch_booking(booking_id)
        except httpx.HTTPError:
            respond(f"Could not fetch booking `{booking_id}`.")
            return

        vehicle = booking.get("vehicle", {})
        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*Return Request* 🔁\n"
                        f"Booking: `{booking_id}`\n"
                        f"Vehicle: {vehicle.get('brand', '-')}"
                        f" {vehicle.get('model_name', '-')}"
                        f" ({vehicle.get('plate', '-')})\n"
                        f"Customer: {booking.get('customer', {}).get('name', '-')}"
                    ),
                },
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Mark as Returned"},
                        "style": "primary",
                        "value": booking_id,
                        "action_id": "mark_returned",
                    }
                ],
            },
        ]
        app.client.chat_postMessage(channel="#pickup-managers", blocks=blocks, text=f"Return request {booking_id}")
        respond(f"Posted return request for booking `{booking_id}`.")

    @app.action("mark_returned")
    def mark_returned(ack, body, client):
        """Mark booking as completed from Slack action."""
        ack()
        booking_id = body["actions"][0]["value"]
        httpx.patch(
            f"{BACKEND_URL}/api/bookings/{booking_id}",
            json={"status": "completed"},
            headers=_backend_headers(),
            timeout=20.0,
        ).raise_for_status()
        returned_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
        client.chat_update(
            channel=body["channel"]["id"],
            ts=body["message"]["ts"],
            text=f"✅ Returned at {returned_at}",
        )

    @app.command("/status")
    def booking_status(ack, body, respond):
        """Return booking status summary in Block Kit."""
        ack()
        booking_id = body.get("text", "").strip()
        if not booking_id:
            respond("Usage: `/status <booking_id>`")
            return

        try:
            booking = _fetch_booking(booking_id)
        except httpx.HTTPError:
            respond(f"Could not fetch booking `{booking_id}`.")
            return

        vehicle = booking.get("vehicle", {})
        customer = booking.get("customer", {})
        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*Booking Status* 📌\n"
                        f"Booking: `{booking_id}`\n"
                        f"Status: *{booking.get('status', '-') }*"
                    ),
                },
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Customer:*\n{customer.get('name', '-')}"},
                    {
                        "type": "mrkdwn",
                        "text": (
                            f"*Vehicle:*\n{vehicle.get('brand', '-')}"
                            f" {vehicle.get('model_name', '-')}"
                        ),
                    },
                ],
            },
        ]
        respond(blocks=blocks, text=f"Status for booking {booking_id}")

    @app.command("/fleet")
    def fleet_status(ack, respond):
        """Return fleet count summary."""
        ack()
        try:
            available, rented, maintenance = _fleet_status_counts()
        except httpx.HTTPError:
            respond("Could not fetch fleet status.")
            return
        respond(f"🚗 Fleet Status: {available} available, {rented} rented, {maintenance} maintenance")

if __name__ == "__main__":
    if app is None or not SLACK_APP_TOKEN:
        print("Slack tokens not configured. Bot listener is disabled.")
        while True:
            time.sleep(3600)
    SocketModeHandler(app, SLACK_APP_TOKEN).start()
