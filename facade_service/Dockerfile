FROM python:3.11-slim

WORKDIR /app
COPY . /app

RUN pip install fastapi uvicorn httpx

EXPOSE 8001
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]