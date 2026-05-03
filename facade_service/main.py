from fastapi import FastAPI, HTTPException
from contextlib import asynccontextmanager
from pydantic import BaseModel
import uuid
import httpx
import time
import random
import os
import hazelcast
import asyncio

CONSUL_URL = os.getenv("CONSUL_URL", "http://consul:8500")

SERVICE_NAME = "facade-service"
SERVICE_HOST = os.getenv("SERVICE_HOST", "facade_service")
SERVICE_PORT = int(os.getenv("SERVICE_PORT", "8001"))
SERVICE_ID = os.getenv("SERVICE_ID", f"{SERVICE_NAME}-{SERVICE_HOST}-{SERVICE_PORT}")
SERVICE_URL = f"http://{SERVICE_HOST}:{SERVICE_PORT}"

DEFAULT_MQ_HOSTS = "hazelcast1:5701,hazelcast2:5701,hazelcast3:5701"
DEFAULT_MQ_CLUSTER_NAME = "dev"
DEFAULT_QUEUE_NAME = "counter-queue"

DISCOVERY_CACHE_SECONDS = 5
LOG_EVERY = int(os.getenv("LOG_EVERY", "1000"))

REQUEST_TIMEOUT = httpx.Timeout(
    connect=10.0,
    read=120.0,
    write=30.0,
    pool=30.0,
)

HTTP_LIMITS = httpx.Limits(
    max_connections=100,
    max_keepalive_connections=50,
)

hz_client = None
tx_queue = None
http_client = None

service_cache = {}

total_logging_time = 0.0
total_counter_time = 0.0
request_count = 0


class IncomingTransaction(BaseModel):
    user_id: str
    amount: float


async def consul_get_value(key: str, default: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{CONSUL_URL}/v1/kv/{key}?raw=true")

        if response.status_code == 200:
            return response.text.strip()

        print(f"Facade: Consul KV key '{key}' not found, using default: {default}")
        return default

    except Exception as e:
        print(f"Facade: could not read Consul KV key '{key}': {e}")
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

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.put(
            f"{CONSUL_URL}/v1/agent/service/register",
            json=payload,
        )
        response.raise_for_status()

    print(f"Facade: registered in Consul as {SERVICE_ID} at {SERVICE_URL}")


async def deregister_service():
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.put(f"{CONSUL_URL}/v1/agent/service/deregister/{SERVICE_ID}")

        print(f"Facade: deregistered from Consul: {SERVICE_ID}")

    except Exception as e:
        print(f"Facade: could not deregister from Consul: {e}")


async def discover_service_urls(service_name: str, force_refresh: bool = False):
    global service_cache, http_client

    if http_client is None:
        raise RuntimeError("HTTP client is not initialized")

    now = time.time()
    cached = service_cache.get(service_name)

    if (
        not force_refresh
        and cached is not None
        and cached["expires_at"] > now
        and cached["urls"]
    ):
        return cached["urls"]

    response = await http_client.get(
        f"{CONSUL_URL}/v1/health/service/{service_name}?passing=true"
    )
    response.raise_for_status()

    services = response.json()

    urls = []
    for instance in services:
        address = instance["Service"]["Address"]
        port = instance["Service"]["Port"]
        urls.append(f"http://{address}:{port}")

    if not urls:
        raise RuntimeError(f"No healthy instances found for {service_name}")

    service_cache[service_name] = {
        "urls": urls,
        "expires_at": now + DISCOVERY_CACHE_SECONDS,
    }

    return urls


async def request_service(method: str, service_name: str, path: str, **kwargs):
    global http_client

    if http_client is None:
        raise HTTPException(status_code=503, detail="HTTP client is not initialized")

    try:
        urls = await discover_service_urls(service_name)
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"Could not discover {service_name}: {e}",
        )

    shuffled_urls = urls[:]
    random.shuffle(shuffled_urls)

    last_error = None

    for base_url in shuffled_urls:
        try:
            response = await http_client.request(
                method,
                f"{base_url}{path}",
                **kwargs,
            )
            response.raise_for_status()
            return response

        except Exception as e:
            last_error = e

    # If cached instances failed, refresh Consul once and retry.
    try:
        fresh_urls = await discover_service_urls(service_name, force_refresh=True)
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"Could not refresh {service_name}: {e}",
        )

    random.shuffle(fresh_urls)

    for base_url in fresh_urls:
        try:
            response = await http_client.request(
                method,
                f"{base_url}{path}",
                **kwargs,
            )
            response.raise_for_status()
            return response

        except Exception as e:
            last_error = e

    raise HTTPException(
        status_code=503,
        detail=f"All instances of {service_name} failed: {last_error}",
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    global hz_client, tx_queue, http_client

    http_client = httpx.AsyncClient(
        timeout=REQUEST_TIMEOUT,
        limits=HTTP_LIMITS,
    )

    await register_service()

    mq_hosts = await consul_get_value("message-queue/hosts", DEFAULT_MQ_HOSTS)
    mq_cluster_name = await consul_get_value(
        "message-queue/cluster-name",
        DEFAULT_MQ_CLUSTER_NAME,
    )
    queue_name = await consul_get_value("message-queue/queue-name", DEFAULT_QUEUE_NAME)

    hz_client = hazelcast.HazelcastClient(
        cluster_members=[host.strip() for host in mq_hosts.split(",")],
        cluster_name=mq_cluster_name,
    )

    tx_queue = hz_client.get_queue(queue_name).blocking()

    print(
        f"Facade: connected to MQ hosts={mq_hosts}, "
        f"cluster={mq_cluster_name}, queue={queue_name}"
    )

    yield

    if hz_client:
        hz_client.shutdown()

    await deregister_service()

    if http_client:
        await http_client.aclose()


app = FastAPI(lifespan=lifespan)


@app.get("/health")
def health():
    return {
        "status": "UP",
        "service": SERVICE_NAME,
        "id": SERVICE_ID,
    }


@app.post("/transactions")
async def create_transaction(tx: IncomingTransaction):
    global total_logging_time, total_counter_time, request_count

    if tx_queue is None:
        raise HTTPException(status_code=503, detail="Message queue is not initialized")

    transaction_id = str(uuid.uuid4())
    timestamp = time.time()

    payload = {
        "transaction_id": transaction_id,
        "user_id": tx.user_id,
        "amount": tx.amount,
        "timestamp": str(timestamp),
    }

    t0 = time.perf_counter()
    log_resp = await request_service(
        "POST",
        "logging-service",
        "/log",
        json=payload,
    )
    t1 = time.perf_counter()

    total_logging_time += t1 - t0
    log_status = log_resp.json().get("status")

    t2 = time.perf_counter()
    await asyncio.to_thread(
        tx_queue.put,
        {"user_id": tx.user_id, "amount": tx.amount},
    )
    t3 = time.perf_counter()

    total_counter_time += t3 - t2

    request_count += 1
    if request_count % LOG_EVERY == 0:
        print(
            f"Facade: processed {request_count} transactions, "
            f"last_log_status={log_status}"
        )

    return {
        "transaction_id": transaction_id,
        "status": "queued",
    }


@app.get("/user/{user_id}")
async def get_user_info(user_id: str):
    try:
        bal_resp = await request_service(
            "GET",
            "counter-service",
            f"/user/{user_id}",
        )
        balance = bal_resp.json().get("balance", None)

    except Exception as e:
        print(f"Facade: could not get balance from counter-service: {e}")
        balance = None

    try:
        log_resp = await request_service(
            "GET",
            "logging-service",
            f"/user/{user_id}",
        )
        transactions = log_resp.json().get("transactions", [])

    except Exception as e:
        print(f"Facade: could not get transactions from logging-service: {e}")
        transactions = []

    return {
        "user_id": user_id,
        "balance": balance,
        "transactions": transactions,
    }


@app.get("/accounts")
async def get_all_accounts():
    try:
        response = await request_service(
            "GET",
            "counter-service",
            "/accounts",
        )
        return response.json()

    except Exception as e:
        print(f"Facade: could not get accounts from counter-service: {e}")
        return {"accounts": None}


@app.get("/timing")
def get_timings():
    return {
        "total_logging_time_seconds": total_logging_time,
        "total_counter_time_seconds": total_counter_time,
    }


@app.post("/timing/reset")
def reset_timings():
    global total_logging_time, total_counter_time, request_count

    total_logging_time = 0.0
    total_counter_time = 0.0
    request_count = 0

    return {"status": "reset"}