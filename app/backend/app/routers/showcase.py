from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app import engine
from app.schemas import ShowcaseResponse

router = APIRouter(prefix="/api", tags=["showcase"])


@router.get("/showcase", response_model=ShowcaseResponse)
def showcase() -> dict:
    """Archived T7 self-consistency run + T8 NACA panel sweep + paper figures
    (item 7 of the app rich-features brief): read-only over
    experiments/results/, for the Results Gallery page and the Theater's
    'replay archived T7' instant-demo button."""
    try:
        return engine.run_showcase()
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"showcase failed: {type(exc).__name__}: {exc}"
        ) from exc
