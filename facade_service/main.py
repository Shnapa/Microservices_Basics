import random
import time
import uuid

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI()

LOGGING_INSTANCES = [
    "http://logging_service_1:8002",
    "http://logging_service_2:8002",
    "http://logging_service_3:8002",
]
COUNTER_URL = "http://counter_service:8003"

total_logging_time = 0.0
total_counter_time = 0.0


def pick_logging_url() -> str:
    """Return a randomly ordered list of logging service URLs for fallback."""
    shuffled = LOGGING_INSTANCES.copy()
    random.shuffle(shuffled)
    return shuffled


class IncomingTransaction(BaseModel):
    user_id: str
    amount: float


@app.post("/transactions")
async def create_transaction(tx: IncomingTransaction):
    global total_logging_time, total_counter_time

    transaction_id = str(uuid.uuid4())
    timestamp = str(time.time())

    payload = {
        "transaction_id": transaction_id,
        "user_id": tx.user_id,
        "amount": tx.amount,
        "timestamp": timestamp,
    }

    log_status = None
    handled_by = None

    async with httpx.AsyncClient(timeout=5.0) as client:
        t0 = time.perf_counter()
        for url in pick_logging_url():
            try:
                log_resp = await client.post(f"{url}/log", json=payload)
                log_data = log_resp.json()
                log_status = log_data.get("status")
                handled_by = log_data.get("handled_by", url)
                break
            except Exception as e:
                print(f"Facade: logging instance {url} unavailable: {e}, trying next...")
        t1 = time.perf_counter()
        total_logging_time += (t1 - t0)

        if log_status is None:
            raise HTTPException(status_code=503, detail="All logging instances unavailable")

        t2 = time.perf_counter()
        counter_resp = await client.post(
            f"{COUNTER_URL}/apply",
            json={"user_id": tx.user_id, "amount": tx.amount},
        )
        t3 = time.perf_counter()
        total_counter_time += (t3 - t2)

    new_balance = counter_resp.json().get("balance")

    print(
        f"Facade: tx={transaction_id} user={tx.user_id} amount={tx.amount} "
        f"log_status={log_status} handled_by={handled_by} balance={new_balance}"
    )

    return {
        "transaction_id": transaction_id,
        "balance": new_balance,
        "logged_by": handled_by,
    }


@app.get("/user/{user_id}")
async def get_user_info(user_id: str):
    async with httpx.AsyncClient(timeout=5.0) as client:
        bal_resp = await client.get(f"{COUNTER_URL}/user/{user_id}")

        transactions = []
        for url in pick_logging_url():
            try:
                log_resp = await client.get(f"{url}/user/{user_id}")
                transactions = log_resp.json().get("transactions", [])
                break
            except Exception as e:
                print(f"Facade: logging instance {url} unavailable for GET: {e}")

    balance = bal_resp.json().get("balance", 0.0)
    return {
        "user_id": user_id,
        "balance": balance,
        "transactions": transactions,
    }


@app.get("/accounts")
async def get_all_accounts():
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(f"{COUNTER_URL}/accounts")
    return resp.json()


@app.get("/messages")
async def get_all_messages():
    """Read all messages from Hazelcast via any available logging instance."""
    async with httpx.AsyncClient(timeout=5.0) as client:
        for url in pick_logging_url():
            try:
                resp = await client.get(f"{url}/messages")
                return resp.json()
            except Exception as e:
                print(f"Facade: logging instance {url} unavailable for /messages: {e}")
    raise HTTPException(status_code=503, detail="All logging instances unavailable")


@app.get("/timing")
def get_timings():
    return {
        "total_logging_time_seconds": total_logging_time,
        "total_counter_time_seconds": total_counter_time,
    }


@app.post("/timing/reset")
def reset_timings():
    global total_logging_time, total_counter_time
    total_logging_time = 0.0
    total_counter_time = 0.0
    return {"status": "reset"}