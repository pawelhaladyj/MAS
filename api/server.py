# api/server.py
from __future__ import annotations

import os
import logging
import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request
from api.routes.chat import router as chat_router
from agents.common.config import settings
from agents.api_bridge import ApiBridgeAgent

logger = logging.getLogger("api.server")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Kolejki: API -> Bridge (inbox), Bridge -> API (outbox)
    app.state.bridge_inbox = asyncio.Queue()
    app.state.bridge_outbox = asyncio.Queue()

    bridge_enabled = os.getenv("API_BRIDGE_ENABLED", "0") == "1"
    if bridge_enabled:
        logger.info("Starting ApiBridgeAgent (API_BRIDGE_ENABLED=1)")
        bridge = ApiBridgeAgent(
            jid=settings.api_bridge_jid,
            password=settings.api_bridge_pass,
            verify_security=settings.verify_security,
            inbox=app.state.bridge_inbox,
            outbox=app.state.bridge_outbox,
        )
        try:
            await bridge.start(auto_register=False)
            app.state.bridge = bridge
            logger.info("ApiBridgeAgent started.")
        except Exception as e:
            logger.error(f"ApiBridgeAgent failed to start: {e}")
            raise
    else:
        logger.info("ApiBridgeAgent disabled (API_BRIDGE_ENABLED!=1)")

    try:
        yield
    finally:
        if getattr(app.state, "bridge", None):
            logger.info("Stopping ApiBridgeAgent...")
            with suppress(Exception):
                await app.state.bridge.stop()
            logger.info("ApiBridgeAgent stopped.")


app = FastAPI(lifespan=lifespan)
app.include_router(chat_router)
