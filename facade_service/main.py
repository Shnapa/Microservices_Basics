from fastapi import FastAPI
from contextlib import asynccontextmanager
from pydantic import BaseModel
import uuid
import httpx
import time
import random
import os
import hazelcast

CONFIG_SERVER_URL = os.getenv("CONFIG_SERVER_URL", "http://config_server:8000")
SERVICE_NAME = "facade-service"
SERVICE_URL = os.getenv("SERVICE_URL", "http://facade_service:8001")
HZ_HOSTS = os.getenv("HZ_HOSTS", "hazelcast1:5701,hazelcast2:5701,hazelcast3:5701")
QUEUE_NAME = "counter-queue"

hz_client = None
tx_queue = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global hz_client, tx_queue

    hz_client = hazelcast.HazelcastClient(
        cluster_members=HZ_HOSTS.split(","),
        cluster_name="dev",
    )

    tx_queue = hz_client.get_queue(QUEUE_NAME).blocking()

    try:
        async with httpx.AsyncClient() as client:
            await client.post(f"{CONFIG_SERVER_URL}/register", json={
                "service": SERVICE_NAME,
                "url": SERVICE_URL,
            })
        print(f"Facade: registered at config-server as {SERVICE_URL}")
    except Exception as e:
        print(f"Facade: could not register at config-server: {e}")

    yield

    hz_client.shutdown()

app = FastAPI(lifespan=lifespan)

async def get_service_url(service_name: str) -> str:
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{CONFIG_SERVER_URL}/services/{service_name}")
        instances = resp.json()
        if not instances:
            raise RuntimeError(f"No instances found for {service_name}")
        return random.choice(instances)

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

    logging_url = await get_service_url("logging-service")
    async with httpx.AsyncClient() as client:
        t0 = time.perf_counter()
        log_resp = await client.post(f"{logging_url}/log", json=payload)
        t1 = time.perf_counter()
        total_logging_time += (t1 - t0)

    log_status = log_resp.json().get("status")

    t2 = time.perf_counter()
    tx_queue.put({"user_id": tx.user_id, "amount": tx.amount})
    t3 = time.perf_counter()
    total_counter_time += (t3 - t2)

    print(f"Facade: tx={transaction_id} user={tx.user_id} amount={tx.amount} log_status={log_status} queued=True")

    return {
        "transaction_id": transaction_id,
        "status": "queued",
    }

@app.get("/user/{user_id}")
async def get_user_info(user_id: str):
    logging_url = await get_service_url("logging-service")

    try:
        counter_url = await get_service_url("counter-service")
        async with httpx.AsyncClient() as client:
            bal_resp = await client.get(f"{counter_url}/user/{user_id}")
        balance = bal_resp.json().get("balance", None)
    except Exception:
        balance = None

    async with httpx.AsyncClient() as client:
        log_resp = await client.get(f"{logging_url}/user/{user_id}")

    transactions = log_resp.json().get("transactions", [])

    return {
        "user_id": user_id,
        "balance": balance,
        "transactions": transactions,
    }

@app.get("/accounts")
async def get_all_accounts():
    try:
        counter_url = await get_service_url("counter-service")
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{counter_url}/accounts")
        return resp.json()
    except Exception:
        return {"accounts": None}

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