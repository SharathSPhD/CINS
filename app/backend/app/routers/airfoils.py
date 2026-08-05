from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app import engine
from app.schemas import AirfoilGeometryResponse, AirfoilListResponse

router = APIRouter(prefix="/api", tags=["airfoils"])


@router.get("/airfoils", response_model=AirfoilListResponse)
def list_airfoils() -> dict:
    """All UIUC sections (data/airfoils/uiuc, cached thickness/camber summary
    from a one-time fit scan) + a curated NACA generator preset list."""
    try:
        return engine.list_airfoils()
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"airfoil listing failed: {type(exc).__name__}: {exc}"
        ) from exc


@router.get("/airfoils/{airfoil_id:path}/geometry", response_model=AirfoilGeometryResponse)
def airfoil_geometry(airfoil_id: str) -> dict:
    """``airfoil_id`` is ``"uiuc:<name>"`` or ``"naca:<code>"`` (as returned
    by ``GET /api/airfoils``)."""
    try:
        return engine.get_airfoil_geometry(airfoil_id)
    except engine.EngineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail=f"geometry lookup failed: {type(exc).__name__}: {exc}"
        ) from exc
