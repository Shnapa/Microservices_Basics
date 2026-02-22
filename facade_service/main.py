from fastapi import FastAPI
from pydantic import BaseModel
import uuid
import httpx
import time

app = FastAPI()

LOGGING_URL = "http://127.0.0.1:8002"
COUNTER_URL = "http://127.0.0.1:8003"


class IncomingTransaction(BaseModel):
    user_id: str
    amount: float


total_logging_time = 0.0
total_counter_time = 0.0


@app.post("/transactions")
async def create_transaction(tx: IncomingTransaction):
    global total_logging_time, total_counter_time

    transaction_id = str(uuid.uuid4())
    timestamp = time.time()

    payload = {
        "transaction_id": transaction_id,
        "user_id": tx.user_id,
        "amount": tx.amount,
        "timestamp": str(timestamp),
    }

    async with httpx.AsyncClient() as client:
        t0 = time.perf_counter()
        log_resp = await client.post(f"{LOGGING_URL}/log", json=payload)
        t1 = time.perf_counter()
        total_logging_time += (t1 - t0)

        t2 = time.perf_counter()
        counter_resp = await client.post(
            f"{COUNTER_URL}/apply",
            json={"user_id": tx.user_id, "amount": tx.amount},
        )
        t3 = time.perf_counter()
        total_counter_time += (t3 - t2)

    log_status = log_resp.json().get("status")
    new_balance = counter_resp.json().get("balance")

    print(
        f"Facade: tx={transaction_id} user={tx.user_id} amount={tx.amount} "
        f"log_status={log_status} balance={new_balance}"
    )

    return {
        "transaction_id": transaction_id,
        "balance": new_balance,
    }


@app.get("/user/{user_id}")
async def get_user_info(user_id: str):
    async with httpx.AsyncClient() as client:
        bal_resp = await client.get(f"{COUNTER_URL}/user/{user_id}")
        log_resp = await client.get(f"{LOGGING_URL}/user/{user_id}")

    balance = bal_resp.json().get("balance", 0.0)
    transactions = log_resp.json().get("transactions", [])

    return {
        "user_id": user_id,
        "balance": balance,
        "transactions": transactions,
    }


@app.get("/accounts")
async def get_all_accounts():
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{COUNTER_URL}/accounts")
    return resp.json()


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
