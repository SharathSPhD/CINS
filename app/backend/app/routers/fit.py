from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app import engine
from app.schemas import FitRequest, FitResponse

router = APIRouter(prefix="/api", tags=["fit"])


@router.post("/fit", response_model=FitResponse)
def fit(req: FitRequest) -> dict:
    try:
        return engine.run_fit(req)
    except engine.EngineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail=f"fit failed: {type(exc).__name__}: {exc}"
        ) from exc
