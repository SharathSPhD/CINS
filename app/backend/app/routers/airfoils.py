from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile

from app import engine
from app.schemas import AirfoilGeometryResponse, AirfoilListResponse, AirfoilUploadResponse

router = APIRouter(prefix="/api", tags=["airfoils"])

_MAX_UPLOAD_BYTES = 1_000_000  # a .dat coordinate file is a few KB; generous cap


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


@router.post("/airfoils/upload", response_model=AirfoilUploadResponse)
async def upload_airfoil(file: UploadFile = File(...)) -> dict:
    """Item 6 of the app rich-features brief: a user-supplied ``.dat`` file
    (Selig or Lednicer, autodetected: same loader as the UIUC corpus),
    parsed + CST-fitted so it can drive Analyze/FlowField/Inverse straight
    from the browser."""
    content = await file.read()
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="file too large (limit 1 MB)")
    try:
        return engine.run_airfoil_upload(file.filename or "upload.dat", content)
    except engine.EngineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail=f"upload parse failed: {type(exc).__name__}: {exc}"
        ) from exc
