from fastapi import FastAPI
from contextlib import asynccontextmanager
from typing import Dict
import threading
import httpx
import os
import hazelcast

CONSUL_URL = os.getenv("CONSUL_URL", "http://consul:8500")

SERVICE_NAME = "counter-service"
SERVICE_HOST = os.getenv("SERVICE_HOST", "counter_service")
SERVICE_PORT = int(os.getenv("SERVICE_PORT", "8003"))
SERVICE_ID = os.getenv("SERVICE_ID", f"{SERVICE_NAME}-{SERVICE_HOST}-{SERVICE_PORT}")
SERVICE_URL = f"http://{SERVICE_HOST}:{SERVICE_PORT}"

DEFAULT_MQ_HOSTS = "hazelcast1:5701,hazelcast2:5701,hazelcast3:5701"
DEFAULT_MQ_CLUSTER_NAME = "dev"
DEFAULT_QUEUE_NAME = "counter-queue"

balances: Dict[str, float] = {}
hz_client = None
queue_name = DEFAULT_QUEUE_NAME


async def consul_get_value(key: str, default: str) -> str:
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{CONSUL_URL}/v1/kv/{key}?raw=true")

        if response.status_code == 200:
            return response.text.strip()

        print(f"Counter: Consul KV key '{key}' not found, using default: {default}")
        return default
    except Exception as e:
        print(f"Counter: could not read Consul KV key '{key}': {e}")
        return default


async def register_service():
    payload = {
        "ID": SERVICE_ID,
        "Name": SERVICE_NAME,
        "Address": SERVICE_HOST,
        "Port": SERVICE_PORT,
        "Check": {
            "HTTP": f"{SERVICE_URL}/health",
            "Interval": "5s",
            "Timeout": "2s",
            "DeregisterCriticalServiceAfter": "30s",
        },
    }

    async with httpx.AsyncClient() as client:
        response = await client.put(
            f"{CONSUL_URL}/v1/agent/service/register",
            json=payload,
        )
        response.raise_for_status()

    print(f"Counter: registered in Consul as {SERVICE_ID} at {SERVICE_URL}")


async def deregister_service():
    try:
        async with httpx.AsyncClient() as client:
            await client.put(f"{CONSUL_URL}/v1/agent/service/deregister/{SERVICE_ID}")
        print(f"Counter: deregistered from Consul: {SERVICE_ID}")
    except Exception as e:
        print(f"Counter: could not deregister from Consul: {e}")


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

            if int(balances[user_id]) % 1000 == 0:
                print(f"Counter: user={user_id} balance={balances[user_id]}")

        except Exception as e:
            print(f"Counter: queue error: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global hz_client, queue_name

    await register_service()

    mq_hosts = await consul_get_value("message-queue/hosts", DEFAULT_MQ_HOSTS)
    mq_cluster_name = await consul_get_value(
        "message-queue/cluster-name",
        DEFAULT_MQ_CLUSTER_NAME,
    )
    queue_name = await consul_get_value("message-queue/queue-name", DEFAULT_QUEUE_NAME)

    hz_client = hazelcast.HazelcastClient(
        cluster_members=mq_hosts.split(","),
        cluster_name=mq_cluster_name,
    )

    queue = hz_client.get_queue(queue_name).blocking()

    thread = threading.Thread(target=consume_queue, args=(queue,), daemon=True)
    thread.start()

    print(
        f"Counter: connected to MQ hosts={mq_hosts}, "
        f"cluster={mq_cluster_name}, queue={queue_name}"
    )

    yield

    if hz_client:
        hz_client.shutdown()

    await deregister_service()


app = FastAPI(lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "UP", "service": SERVICE_NAME, "id": SERVICE_ID}


@app.get("/user/{user_id}")
def get_user_balance(user_id: str):
    return {"user_id": user_id, "balance": balances.get(user_id, None)}


@app.get("/accounts")
def get_all_accounts():
    return {"accounts": balances}