from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app import engine
from app.schemas import GeometryFromCSTRequest, GeometryFromCSTResponse

router = APIRouter(prefix="/api", tags=["geometry"])


@router.post("/geometry/from-cst", response_model=GeometryFromCSTResponse)
def geometry_from_cst(req: GeometryFromCSTRequest) -> dict:
    """Instant CST -> coordinates (for live slider morphing) + the derived
    engineering-parameter readout (LE radius, TE wedge, t/c, camber, area)."""
    try:
        return engine.run_geometry_from_cst(req)
    except engine.EngineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail=f"geometry-from-cst failed: {type(exc).__name__}: {exc}"
        ) from exc
