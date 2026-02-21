from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class LogMessage(BaseModel):
    uuid: str
    msg: str

messages_store: dict[str, str] = {}

@app.post("/log")
def log_message(data: LogMessage):
    if data.uuid in messages_store:
        print(f"Duplicate message ignored: {data.uuid} -> {data.msg}")
        return {"status": "duplicate_ignored"}

    messages_store[data.uuid] = data.msg
    print(f"Logged: {data.uuid} -> {data.msg}")
    return {"status": "logged"}

@app.get("/messages")
def get_messages():
    all_msgs = " | ".join(messages_store.values())
    return {"messages": all_msgs}