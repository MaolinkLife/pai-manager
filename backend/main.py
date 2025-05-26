from fastapi import FastAPI
from routes.ollama_routes import router as ollama_router
from routes.config_routes import router as config_router

from config import config_loader

config_loader.ensure_config_exists()

app = FastAPI()
app.include_router(ollama_router)
app.include_router(config_router)


@app.get("/api/ping")
def ping():
    return {"message": "pong"}
