# api/server.py (fragmenty)
import os
import logging
from fastapi import FastAPI
from api.routes.chat import router as chat_router

app = FastAPI()
app.include_router(chat_router)

logger = logging.getLogger("api.server")

# (jeżeli masz jakieś istniejące on_event startup, owiń je if-em)
@app.on_event("startup")
async def startup():
    if os.getenv("ENABLE_API_AGENTS", "0") != "1":
        logger.info("API: agents not started (ENABLE_API_AGENTS!=1)")
        return
    # tu ewentualnie później wystartujemy bridge / agentów, ale nie teraz
