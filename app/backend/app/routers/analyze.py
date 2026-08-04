from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app import engine
from app.schemas import AnalyzeRequest, AnalyzeResponse

router = APIRouter(prefix="/api", tags=["analyze"])


@router.post("/analyze", response_model=AnalyzeResponse)
def analyze(req: AnalyzeRequest) -> dict:
    try:
        return engine.run_analyze(req)
    except engine.EngineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # unexpected mfoil/engine failure
        raise HTTPException(
            status_code=400, detail=f"analyze failed: {type(exc).__name__}: {exc}"
        ) from exc
