from fastapi import FastAPI
from contextlib import asynccontextmanager
from typing import Dict
import threading
import httpx
import os
import hazelcast

CONFIG_SERVER_URL = os.getenv("CONFIG_SERVER_URL", "http://config_server:8000")
SERVICE_NAME = "counter-service"
SERVICE_URL = os.getenv("SERVICE_URL", "http://counter_service:8003")
HZ_HOSTS = os.getenv("HZ_HOSTS", "hazelcast1:5701,hazelcast2:5701,hazelcast3:5701")
QUEUE_NAME = "counter-queue"

balances: Dict[str, float] = {}
hz_client = None

def consume_queue(queue):
    while True:
        try:
            msg = queue.poll(timeout=1)
            if msg is None:
                continue
            user_id = msg["user_id"]
            amount = msg["amount"]
            current = balances.get(user_id, 0.0)
            balances[user_id] = current + amount
            print(f"Counter: consumed user={user_id} amount={amount} new_balance={balances[user_id]}")
        except Exception as e:
            print(f"Counter: queue error: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    global hz_client

    hz_client = hazelcast.HazelcastClient(
        cluster_members=HZ_HOSTS.split(","),
        cluster_name="dev",
    )

    queue = hz_client.get_queue(QUEUE_NAME).blocking()

    thread = threading.Thread(target=consume_queue, args=(queue,), daemon=True)
    thread.start()

    try:
        async with httpx.AsyncClient() as client:
            await client.post(f"{CONFIG_SERVER_URL}/register", json={
                "service": SERVICE_NAME,
                "url": SERVICE_URL,
            })
        print(f"Counter: registered at config-server as {SERVICE_URL}")
    except Exception as e:
        print(f"Counter: could not register at config-server: {e}")

    yield

    hz_client.shutdown()

app = FastAPI(lifespan=lifespan)

@app.get("/user/{user_id}")
def get_user_balance(user_id: str):
    return {"user_id": user_id, "balance": balances.get(user_id, None)}

@app.get("/accounts")
def get_all_accounts():
    return {"accounts": balances}