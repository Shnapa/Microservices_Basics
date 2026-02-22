from fastapi import FastAPI
from pydantic import BaseModel
from typing import Dict, List
from datetime import datetime

app = FastAPI()


class Transaction(BaseModel):
    transaction_id: str
    user_id: str
    amount: float
    timestamp: str


transactions_by_user: Dict[str, List[Transaction]] = {}


@app.post("/log")
def log_transaction(tx: Transaction):
    """Store transaction in memory."""
    user_tx = transactions_by_user.setdefault(tx.user_id, [])
    user_tx.append(tx)
    print(f"Logged tx: {tx.transaction_id} user={tx.user_id} amount={tx.amount}")
    return {"status": "logged"}


@app.get("/user/{user_id}")
def get_user_transactions(user_id: str):
    """Return all transactions for a given user."""
    txs = transactions_by_user.get(user_id, [])
    return {"user_id": user_id, "transactions": txs}
