from fastapi import FastAPI
from contextlib import asynccontextmanager
from pydantic import BaseModel
from typing import Dict, List
import httpx
import os

CONFIG_SERVER_URL = os.getenv("CONFIG_SERVER_URL", "http://config_server:8000")
SERVICE_NAME = "logging-service"
SERVICE_URL = os.getenv("SERVICE_URL", "http://logging_service_1:8002")

class Transaction(BaseModel):
    transaction_id: str
    user_id: str
    amount: float
    timestamp: str

transactions_by_user: Dict[str, List[Transaction]] = {}

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        async with httpx.AsyncClient() as client:
            await client.post(f"{CONFIG_SERVER_URL}/register", json={
                "service": SERVICE_NAME,
                "url": SERVICE_URL,
            })
        print(f"Logging: registered at config-server as {SERVICE_URL}")
    except Exception as e:
        print(f"Logging: could not register at config-server: {e}")
    yield

app = FastAPI(lifespan=lifespan)

@app.post("/log")
def log_transaction(tx: Transaction):
    user_tx = transactions_by_user.setdefault(tx.user_id, [])
    user_tx.append(tx)
    print(f"Logging [{SERVICE_URL}]: tx={tx.transaction_id} user={tx.user_id} amount={tx.amount}")
    return {"status": "logged"}

@app.get("/user/{user_id}")
def get_user_transactions(user_id: str):
    txs = transactions_by_user.get(user_id, [])
    return {"user_id": user_id, "transactions": txs}