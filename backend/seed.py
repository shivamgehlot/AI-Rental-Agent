"""Seed demo data for RideSwift."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import chromadb
from sqlalchemy import delete

from auth import hash_password
from database import AsyncSessionLocal
from models import Booking, Customer, InsuranceDocument, Vehicle


def _vehicle_seed_data() -> list[dict]:
    """Return fixed demo inventory for all 15 vehicles."""
    return [
        {"type": "sedan", "brand": "Toyota", "model_name": "Camry", "plate": "KA01AA1001", "daily_rate": Decimal("45.00"), "location": "Airport", "status": "available"},
        {"type": "sedan", "brand": "Honda", "model_name": "Accord", "plate": "KA01AA1002", "daily_rate": Decimal("45.00"), "location": "City Center", "status": "available"},
        {"type": "sedan", "brand": "Hyundai", "model_name": "Verna", "plate": "KA01AA1003", "daily_rate": Decimal("45.00"), "location": "Mall", "status": "available"},
        {"type": "suv", "brand": "Mahindra", "model_name": "XUV700", "plate": "KA01BB2001", "daily_rate": Decimal("75.00"), "location": "Airport", "status": "rented"},
        {"type": "suv", "brand": "Tata", "model_name": "Safari", "plate": "KA01BB2002", "daily_rate": Decimal("75.00"), "location": "Railway Station", "status": "available"},
        {"type": "suv", "brand": "Kia", "model_name": "Seltos", "plate": "KA01BB2003", "daily_rate": Decimal("75.00"), "location": "City Center", "status": "available"},
        {"type": "hatchback", "brand": "Maruti", "model_name": "Swift", "plate": "KA01CC3001", "daily_rate": Decimal("30.00"), "location": "Mall", "status": "available"},
        {"type": "hatchback", "brand": "Hyundai", "model_name": "i20", "plate": "KA01CC3002", "daily_rate": Decimal("30.00"), "location": "Airport", "status": "available"},
        {"type": "hatchback", "brand": "Tata", "model_name": "Altroz", "plate": "KA01CC3003", "daily_rate": Decimal("30.00"), "location": "Railway Station", "status": "maintenance"},
        {"type": "ev", "brand": "Tata", "model_name": "Nexon EV", "plate": "KA01DD4001", "daily_rate": Decimal("60.00"), "location": "City Center", "status": "available"},
        {"type": "ev", "brand": "MG", "model_name": "ZS EV", "plate": "KA01DD4002", "daily_rate": Decimal("60.00"), "location": "Airport", "status": "rented"},
        {"type": "ev", "brand": "BYD", "model_name": "Atto 3", "plate": "KA01DD4003", "daily_rate": Decimal("60.00"), "location": "Mall", "status": "available"},
        {"type": "bike", "brand": "Royal Enfield", "model_name": "Classic", "plate": "KA01EE5001", "daily_rate": Decimal("15.00"), "location": "Railway Station", "status": "available"},
        {"type": "bike", "brand": "KTM", "model_name": "Duke 390", "plate": "KA01EE5002", "daily_rate": Decimal("15.00"), "location": "City Center", "status": "available"},
        {"type": "bike", "brand": "Bajaj", "model_name": "Pulsar", "plate": "KA01EE5003", "daily_rate": Decimal("15.00"), "location": "Airport", "status": "available"},
    ]


async def seed_database() -> None:
    """Seed vehicles, customers, bookings, and insurance metadata."""
    async with AsyncSessionLocal() as session:
        await session.execute(delete(Booking))
        await session.execute(delete(InsuranceDocument))
        await session.execute(delete(Vehicle))
        await session.execute(delete(Customer))
        await session.commit()

        vehicles: list[Vehicle] = []
        for data in _vehicle_seed_data():
            vehicle = Vehicle(**data)
            session.add(vehicle)
            vehicles.append(vehicle)

        demo_customer = Customer(
            name="Demo User",
            email="demo@rideswift.com",
            phone="+919900000001",
            hashed_password=hash_password("Demo@123"),
            preferences={"preferred_type": "suv", "past_selections": ["suv", "sedan"]},
            loyalty_points=120,
        )
        manager_customer = Customer(
            name="Manager User",
            email="manager@rideswift.com",
            phone="+919900000002",
            hashed_password=hash_password("Manager@123"),
            preferences={"preferred_type": "sedan", "past_selections": ["sedan"]},
            loyalty_points=50,
        )
        test_customer = Customer(
            name="Test User",
            email="test@rideswift.com",
            phone="+919900000003",
            hashed_password=hash_password("Test@123"),
            preferences={"preferred_type": "bike", "past_selections": ["bike"]},
            loyalty_points=20,
        )
        session.add_all([demo_customer, manager_customer, test_customer])
        await session.flush()

        now = datetime.now(UTC)
        active_booking = Booking(
            customer_id=demo_customer.id,
            vehicle_id=vehicles[3].id,
            pickup_date=now - timedelta(days=1),
            return_date=now + timedelta(days=2),
            status="active",
            total_amount=Decimal("225.00"),
            insurance_validated=True,
            notes="Airport pickup confirmed",
        )
        completed_booking = Booking(
            customer_id=demo_customer.id,
            vehicle_id=vehicles[1].id,
            pickup_date=now - timedelta(days=10),
            return_date=now - timedelta(days=7),
            actual_return_date=now - timedelta(days=7),
            status="completed",
            total_amount=Decimal("135.00"),
            insurance_validated=True,
            notes="Completed without issues",
        )
        session.add_all([active_booking, completed_booking])

        insurance_document = InsuranceDocument(
            customer_id=demo_customer.id,
            filename="demo_policy.txt",
            storage_path="seed://insurance/demo_policy.txt",
            chroma_collection=f"insurance_{demo_customer.id}",
        )
        session.add(insurance_document)
        await session.commit()

        customer_id = str(demo_customer.id)

    policy_text = (
        "RideSwift Insurance Policy\n"
        "Third party liability: covered up to ₹15,00,000.\n"
        "Own damage: covered for accidents.\n"
        "Theft: covered with FIR copy.\n"
        "Personal accident: ₹5,00,000 per occupant.\n"
        "Flood damage: NOT covered.\n"
    )

    chroma_client = chromadb.HttpClient(host="chroma", port=8000)
    collection = chroma_client.get_or_create_collection(name=f"insurance_{customer_id}")
    collection.upsert(
        ids=[f"policy-{uuid4()}"],
        documents=[policy_text],
        metadatas=[{"customer_id": customer_id, "source": "seed"}],
    )

    print("Seed completed:")
    print("- 15 vehicles inserted")
    print("- 3 demo customers inserted")
    print("- 2 sample bookings inserted")
    print(f"- Insurance text ingested into Chroma collection insurance_{customer_id}")


if __name__ == "__main__":
    asyncio.run(seed_database())
