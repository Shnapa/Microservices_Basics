from fastapi import FastAPI
from contextlib import asynccontextmanager
from pydantic import BaseModel
from typing import List
import httpx
import os
import hazelcast

CONSUL_URL = os.getenv("CONSUL_URL", "http://consul:8500")

SERVICE_NAME = "logging-service"
SERVICE_HOST = os.getenv("SERVICE_HOST", "logging_service")
SERVICE_PORT = int(os.getenv("SERVICE_PORT", "8002"))
SERVICE_ID = os.getenv("SERVICE_ID", f"{SERVICE_NAME}-{SERVICE_HOST}-{SERVICE_PORT}")
SERVICE_URL = f"http://{SERVICE_HOST}:{SERVICE_PORT}"

DEFAULT_HZ_HOSTS = "hazelcast1:5701,hazelcast2:5701,hazelcast3:5701"
DEFAULT_HZ_CLUSTER_NAME = "dev"
DEFAULT_HZ_MAP_NAME = "transactions-by-user"

hz_client = None
transactions_map = None


class Transaction(BaseModel):
    transaction_id: str
    user_id: str
    amount: float
    timestamp: str


def transaction_to_dict(tx: Transaction) -> dict:
    if hasattr(tx, "model_dump"):
        return tx.model_dump()
    return tx.dict()


async def consul_get_value(key: str, default: str) -> str:
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{CONSUL_URL}/v1/kv/{key}?raw=true")

        if response.status_code == 200:
            return response.text.strip()

        print(f"Logging: Consul KV key '{key}' not found, using default: {default}")
        return default
    except Exception as e:
        print(f"Logging: could not read Consul KV key '{key}': {e}")
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

    print(f"Logging: registered in Consul as {SERVICE_ID} at {SERVICE_URL}")


async def deregister_service():
    try:
        async with httpx.AsyncClient() as client:
            await client.put(f"{CONSUL_URL}/v1/agent/service/deregister/{SERVICE_ID}")
        print(f"Logging: deregistered from Consul: {SERVICE_ID}")
    except Exception as e:
        print(f"Logging: could not deregister from Consul: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global hz_client, transactions_map

    await register_service()

    hz_hosts = await consul_get_value("hazelcast/hosts", DEFAULT_HZ_HOSTS)
    hz_cluster_name = await consul_get_value("hazelcast/cluster-name", DEFAULT_HZ_CLUSTER_NAME)
    hz_map_name = await consul_get_value("hazelcast/map-name", DEFAULT_HZ_MAP_NAME)

    hz_client = hazelcast.HazelcastClient(
        cluster_members=hz_hosts.split(","),
        cluster_name=hz_cluster_name,
    )

    transactions_map = hz_client.get_map(hz_map_name).blocking()

    print(
        f"Logging: connected to Hazelcast hosts={hz_hosts}, "
        f"cluster={hz_cluster_name}, map={hz_map_name}"
    )

    yield

    if hz_client:
        hz_client.shutdown()

    await deregister_service()


app = FastAPI(lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "UP", "service": SERVICE_NAME, "id": SERVICE_ID}


@app.post("/log")
def log_transaction(tx: Transaction):
    tx_dict = transaction_to_dict(tx)

    user_transactions: List[dict] = transactions_map.get(tx.user_id)

    if user_transactions is None:
        user_transactions = []

    user_transactions.append(tx_dict)
    transactions_map.put(tx.user_id, user_transactions)

    print(
        f"Logging [{SERVICE_ID}]: tx={tx.transaction_id} "
        f"user={tx.user_id} amount={tx.amount}"
    )

    return {"status": "logged"}


@app.get("/user/{user_id}")
def get_user_transactions(user_id: str):
    txs = transactions_map.get(user_id)

    if txs is None:
        txs = []

    return {
        "user_id": user_id,
        "transactions": txs,
    }