from fastapi import FastAPI
from pydantic import BaseModel
from typing import Dict

app = FastAPI()


class ApplyRequest(BaseModel):
    user_id: str
    amount: float


balances: Dict[str, float] = {}


@app.post("/apply")
def apply_transaction(req: ApplyRequest):
    """Apply amount to user's balance and return new balance."""
    current = balances.get(req.user_id, 0.0)
    new_balance = current + req.amount
    balances[req.user_id] = new_balance
    print(f"Apply: user={req.user_id} amount={req.amount} new_balance={new_balance}")
    return {"user_id": req.user_id, "balance": new_balance}


@app.get("/user/{user_id}")
def get_user_balance(user_id: str):
    """Return balance for one user."""
    return {"user_id": user_id, "balance": balances.get(user_id, 0.0)}


@app.get("/accounts")
def get_all_accounts():
    """Return balances for all users."""
    return {"accounts": balances}