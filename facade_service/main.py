from fastapi import FastAPI
from pydantic import BaseModel
import uuid
import httpx

app = FastAPI()

LOGGING_URL = "http://127.0.0.1:8002"
MESSAGES_URL = "http://127.0.0.1:8003"


class IncomingMessage(BaseModel):
    msg: str


@app.post("/messages")
async def send_message(payload: IncomingMessage):
    message_id = str(uuid.uuid4())
    print(f"Received from client: {message_id} -> {payload.msg}")

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{LOGGING_URL}/log",
            json={"uuid": message_id, "msg": payload.msg},
        )
    print(f"Forwarded to logging-service, status={resp.status_code}")

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