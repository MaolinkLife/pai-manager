from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routes.ollama_routes import router as ollama_router
from routes.config_routes import router as config_router

from config import config_loader

config_loader.ensure_config_exists()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # или http://localhost:4200
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ollama_router)
app.include_router(config_router)


@app.get("/api/ping")
def ping():
    return {"message": "pong"}
