from fastapi import FastAPI
from pydantic import BaseModel
import uuid
import httpx
import asyncio

app = FastAPI()

LOGGING_URL = "http://127.0.0.1:8002"
MESSAGES_URL = "http://127.0.0.1:8003"


class IncomingMessage(BaseModel):
    msg: str


async def send_to_logging_with_retry(message_id: str, msg: str, retries: int = 3, delay: float = 1.0):
    attempt = 1
    while attempt <= retries:
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.post(
                    f"{LOGGING_URL}/log",
                    json={"uuid": message_id, "msg": msg},
                )
            print(f"Attempt {attempt}: status={resp.status_code}")
            return resp
        except httpx.RequestError as e:
            print(f"Attempt {attempt} failed: {e}")
            if attempt == retries:
                raise
            await asyncio.sleep(delay)
            attempt += 1


@app.post("/messages")
async def send_message(payload: IncomingMessage):
    message_id = str(uuid.uuid4())
    print(f"Received from client: {message_id} -> {payload.msg}")

    resp = await send_to_logging_with_retry(message_id, payload.msg)
    print(f"Forwarded to logging-service, final_status={resp.status_code}, body={resp.json()}")

    return {"uuid": message_id, "status": "stored"}


@app.get("/messages")
async def collect_messages():
    async with httpx.AsyncClient() as client:
        logging_resp = await client.get(f"{LOGGING_URL}/messages")
        messages_resp = await client.get(f"{MESSAGES_URL}/")

    logging_text = logging_resp.json().get("messages", "")
    stub_text = messages_resp.json().get("message", "")

    combined = logging_text + " || " + stub_text
    print(f"Combined response: {combined}")

    return {"result": combined}
