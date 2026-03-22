import os
import json
import hazelcast
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

HZ_HOST = os.getenv("HZ_HOST", "hz1")
HZ_PORT = os.getenv("HZ_PORT", "5701")
SERVICE_NAME = os.getenv("SERVICE_NAME", "logging_service_1")

print(f"[{SERVICE_NAME}] Connecting to Hazelcast at {HZ_HOST}:{HZ_PORT}...")
hz_client = hazelcast.HazelcastClient(
    cluster_name="dev",
    cluster_members=[f"{HZ_HOST}:{HZ_PORT}"],
)
dist_map = hz_client.get_map("transactions-map").blocking()
print(f"[{SERVICE_NAME}] Connected to Hazelcast, using distributed map 'transactions-map'")


class Transaction(BaseModel):
    transaction_id: str
    user_id: str
    amount: float
    timestamp: str


@app.post("/log")
def log_transaction(tx: Transaction):
    key = tx.transaction_id
    value = json.dumps(tx.dict())
    dist_map.put(key, value)
    print(f"[{SERVICE_NAME}] Logged tx: {tx.transaction_id} user={tx.user_id} amount={tx.amount}")
    return {"status": "logged", "handled_by": SERVICE_NAME}


@app.get("/user/{user_id}")
def get_user_transactions(user_id: str):
    all_entries = dist_map.entry_set()
    txs = []
    for key, value in all_entries:
        try:
            entry = json.loads(value)
            if entry.get("user_id") == user_id:
                txs.append(entry)
        except Exception:
            pass
    print(f"[{SERVICE_NAME}] GET transactions for user={user_id}, found {len(txs)}")
    return {"user_id": user_id, "transactions": txs}


@app.get("/messages")
def get_all_messages():
    all_entries = dist_map.entry_set()
    result = []
    for key, value in all_entries:
        try:
            result.append(json.loads(value))
        except Exception:
            pass
    print(f"[{SERVICE_NAME}] GET all messages, total={len(result)}")
    return {"messages": result, "handled_by": SERVICE_NAME}


@app.get("/health")
def health():
    return {"status": "ok", "service": SERVICE_NAME}