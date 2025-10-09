# api/server.py
from __future__ import annotations

import os
import logging
import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from api.routes.chat import router as chat_router

# (opcjonalnie) importy agentów – odkomentuj gdy będziesz ich startował w lifespan
# from agents.agent import BaseAgent
# from agents.api_bridge import ApiBridgeAgent
# from agents.common.config import settings


logger = logging.getLogger("api.server")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan: STARTUP (przed yield) / SHUTDOWN (po yield)."""

    # -------- STARTUP (zastępuje @app.on_event("startup")) --------
    # Przykład jak uruchomić mostek jako task (pozostawiamy wyłączone):
    #
    # bridge = ApiBridgeAgent(
    #     jid=settings.api_bridge_jid,
    #     password=settings.api_bridge_pass,
    #     verify_security=settings.verify_security,
    # )
    # app.state.bridge = bridge
    # app.state.bridge_task = asyncio.create_task(BaseAgent.run_forever(bridge))
    #
    # (tu możesz dodać inne inicjalizacje zasobów)

    yield  # <<< w tym miejscu aplikacja obsługuje żądania

    # -------- SHUTDOWN (zastępuje @app.on_event("shutdown")) --------
    # Porządne zamknięcie tasków agentów, jeśli były uruchomione:
    task = getattr(app.state, "bridge_task", None)
    if task:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    # Jeśli masz jawne API do zatrzymania agenta:
    # bridge = getattr(app.state, "bridge", None)
    # if bridge:
    #     with suppress(Exception):
    #         await bridge.stop()


# UWAGA: tworzymy app *po* zdefiniowaniu lifespan!
app = FastAPI(lifespan=lifespan)
app.include_router(chat_router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api.server:app",
        host=os.getenv("API_HOST", "127.0.0.1"),
        port=int(os.getenv("API_PORT", "8000")),
        reload=False,
    )
