from fastapi import FastAPI
from pydantic import BaseModel
from typing import Dict, List

app = FastAPI()

registry: Dict[str, List[str]] = {}

class RegisterRequest(BaseModel):
    service: str
    url: str

@app.post("/register")
def register(req: RegisterRequest):
    if req.service not in registry:
        registry[req.service] = []
    if req.url not in registry[req.service]:
        registry[req.service].append(req.url)
    print(f"Config: registered {req.service} -> {req.url}")
    return {"status": "registered"}

@app.get("/services/{service_name}")
def get_services(service_name: str):
    return registry.get(service_name, [])

@app.get("/services")
def get_all_services():
    return registry