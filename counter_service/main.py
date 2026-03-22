import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import psycopg2
import psycopg2.extras
import time

app = FastAPI()

DB_HOST = os.getenv("DB_HOST", "postgres")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "counterdb")
DB_USER = os.getenv("DB_USER", "user")
DB_PASS = os.getenv("DB_PASS", "password")


def get_conn():
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT,
        dbname=DB_NAME, user=DB_USER, password=DB_PASS
    )


def init_db():
    for attempt in range(10):
        try:
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS balances (
                    user_id VARCHAR(255) PRIMARY KEY,
                    balance DOUBLE PRECISION NOT NULL DEFAULT 0
                )
            """)
            conn.commit()
            cur.close()
            conn.close()
            print("DB initialized successfully")
            return
        except Exception as e:
            print(f"DB not ready (attempt {attempt+1}/10): {e}")
            time.sleep(3)
    raise RuntimeError("Could not connect to PostgreSQL after 10 attempts")


@app.on_event("startup")
def startup():
    init_db()


class ApplyRequest(BaseModel):
    user_id: str
    amount: float


@app.post("/apply")
def apply_transaction(req: ApplyRequest):
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO balances (user_id, balance)
            VALUES (%s, %s)
            ON CONFLICT (user_id) DO UPDATE
            SET balance = balances.balance + EXCLUDED.balance
            RETURNING balance
        """, (req.user_id, req.amount))
        new_balance = cur.fetchone()[0]
        conn.commit()
        print(f"Apply: user={req.user_id} amount={req.amount} new_balance={new_balance}")
        return {"user_id": req.user_id, "balance": new_balance}
    finally:
        cur.close()
        conn.close()


@app.get("/user/{user_id}")
def get_user_balance(user_id: str):
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT balance FROM balances WHERE user_id = %s", (user_id,))
        row = cur.fetchone()
        balance = row[0] if row else 0.0
        return {"user_id": user_id, "balance": balance}
    finally:
        cur.close()
        conn.close()


@app.get("/accounts")
def get_all_accounts():
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT user_id, balance FROM balances")
        rows = cur.fetchall()
        accounts = {row[0]: row[1] for row in rows}
        return {"accounts": accounts}
    finally:
        cur.close()
        conn.close()