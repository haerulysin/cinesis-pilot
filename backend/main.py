from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

try:  # supports both `uvicorn backend.main:app` and `uvicorn main:app` from backend/
    from .extractor import extract_driver_profile
    from .loads import LOADS
    from .ranker import rank_loads
    from .util import get_logger
except ImportError:
    from extractor import extract_driver_profile
    from loads import LOADS
    from ranker import rank_loads
    from util import get_logger

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR.parent / "frontend"

logger = get_logger("cinesis.api")

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


class ExtractRequest(BaseModel):
    transcript: str


class RankRequest(BaseModel):
    profile: dict[str, Any]
    loads: list[dict[str, Any]]


@app.get("/")
async def root() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/api/loads")
async def get_loads() -> list[dict[str, Any]]:
    return LOADS


@app.post("/api/extract")
async def extract(request: ExtractRequest) -> Any:
    logger.info("Extracting driver profile from transcript")
    try:
        return await asyncio.to_thread(extract_driver_profile, request.transcript)
    except Exception:
        logger.exception("Extraction failed")
        return JSONResponse(status_code=500, content={"error": "extraction failed"})


@app.post("/api/rank")
async def rank(request: RankRequest) -> Any:
    logger.info("Ranking loads for driver profile")
    try:
        return rank_loads(request.profile, request.loads)
    except Exception:
        logger.exception("Ranking failed")
        return JSONResponse(status_code=500, content={"error": "ranking failed"})
