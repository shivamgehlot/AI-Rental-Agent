"""Slack bot for RideSwift notifications."""

from __future__ import annotations

import json
import os
import threading
import time

import httpx
from kafka import KafkaConsumer
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_APP_TOKEN = os.getenv("SLACK_APP_TOKEN")

app: App | None = None
if SLACK_BOT_TOKEN:
    app = App(token=SLACK_BOT_TOKEN)

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
        httpx.patch(f"http://backend:8000/api/bookings/{booking_id}",
                    json={"status": "confirmed"})
        client.chat_update(channel=body["channel"]["id"],
                           ts=body["message"]["ts"],
                           text=f"✅ Booking `{booking_id}` confirmed!")

if __name__ == "__main__":
    if app is None or not SLACK_APP_TOKEN:
        print("Slack tokens not configured. Bot listener is disabled.")
        while True:
            time.sleep(3600)
    SocketModeHandler(app, SLACK_APP_TOKEN).start()
