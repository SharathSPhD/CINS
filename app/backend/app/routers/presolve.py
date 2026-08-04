from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app import engine
from app.schemas import PresolveRequest, PresolveResponse

router = APIRouter(prefix="/api", tags=["presolve"])


@router.post("/presolve", response_model=PresolveResponse)
def presolve(req: PresolveRequest) -> dict:
    """Realisability WARNINGS (``realisable: false``) are not errors — this
    endpoint always returns 200 in that case (ADR-0004); only structurally bad
    requests (unknown constraint, missing coords) raise."""
    try:
        return engine.run_presolve(req)
    except engine.EngineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail=f"presolve failed: {type(exc).__name__}: {exc}"
        ) from exc
