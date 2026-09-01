#!/usr/bin/env python3
"""Seed the IDOR lab database with test users and data."""
import sys
import os
import uuid
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db, User, Order, Message, Document, Invoice

USERS = [
    {"email": "userA@test.com", "password": "userA123!", "name": "Alice Smith",
     "role": "user", "phone": "+1-555-0101", "address": "123 Main St, NYC", "balance": 1500.00},
    {"email": "userB@test.com", "password": "userB123!", "name": "Bob Jones",
     "role": "user", "phone": "+1-555-0202", "address": "456 Oak Ave, LA", "balance": 2750.50},
    {"email": "admin@test.com", "password": "admin123!", "name": "Admin User",
     "role": "admin", "phone": "+1-555-0000", "address": "1 Corp Plaza", "balance": 0.0},
]

ORDERS_A = [
    {"items": json.dumps(["Widget A", "Gadget B"]), "total": 89.99, "status": "delivered"},
    {"items": json.dumps(["Service X"]), "total": 199.00, "status": "pending"},
]

ORDERS_B = [
    {"items": json.dumps(["Premium Plan"]), "total": 499.00, "status": "active"},
    {"items": json.dumps(["Consulting"]), "total": 1200.00, "status": "invoiced"},
]

DOC_UUIDS_A = [str(uuid.uuid4()) for _ in range(3)]
DOC_UUIDS_B = [str(uuid.uuid4()) for _ in range(3)]


def seed():
    with app.app_context():
        db.drop_all()
        db.create_all()

        users = []
        for u in USERS:
            user = User(**u)
            db.session.add(user)
            users.append(user)
        db.session.flush()

        userA, userB, admin = users

        for o in ORDERS_A:
            db.session.add(Order(user_id=userA.id, **o))
        for o in ORDERS_B:
            db.session.add(Order(user_id=userB.id, **o))

        db.session.add(Message(sender_id=userA.id, recipient_id=userB.id,
                               content="Hello Bob! This is Alice's private message."))
        db.session.add(Message(sender_id=userB.id, recipient_id=userA.id,
                               content="Hey Alice! Bob's confidential reply here."))

        for i, uid in enumerate(DOC_UUIDS_A, 1):
            db.session.add(Document(uuid=uid, user_id=userA.id,
                                    title=f"Alice's Document {i}",
                                    content=f"Confidential content for Alice - doc {i}"))
        for i, uid in enumerate(DOC_UUIDS_B, 1):
            db.session.add(Document(uuid=uid, user_id=userB.id,
                                    title=f"Bob's Document {i}",
                                    content=f"Bob's private content - doc {i}"))

        db.session.add(Invoice(user_id=userA.id, amount=350.00, description="Invoice for Alice - Q1 services"))
        db.session.add(Invoice(user_id=userA.id, amount=125.50, description="Invoice for Alice - maintenance"))
        db.session.add(Invoice(user_id=userB.id, amount=2800.00, description="Invoice for Bob - enterprise plan"))
        db.session.add(Invoice(user_id=userB.id, amount=450.00, description="Invoice for Bob - support"))

        db.session.commit()

        print(f"Seeded: {len(users)} users, orders, messages, documents, invoices")
        print(f"UserA ID: {userA.id}, UserB ID: {userB.id}")
        print(f"UserB doc UUIDs: {DOC_UUIDS_B}")

        # Save seed info for tests
        seed_info = {
            "users": [
                {"id": userA.id, "email": userA.email, "password": "userA123!"},
                {"id": userB.id, "email": userB.email, "password": "userB123!"},
                {"id": admin.id, "email": admin.email, "password": "admin123!"},
            ],
            "doc_uuids_b": DOC_UUIDS_B,
        }
        with open("/app/data/seed_info.json", "w") as f:
            json.dump(seed_info, f, indent=2)
        print("Seed info saved to /app/data/seed_info.json")


if __name__ == "__main__":
    seed()
