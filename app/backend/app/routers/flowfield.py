from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app import engine
from app.schemas import FlowFieldRequest, FlowFieldResponse

router = APIRouter(prefix="/api", tags=["flowfield"])


@router.post("/flowfield", response_model=FlowFieldResponse)
def flowfield(req: FlowFieldRequest) -> dict:
    """Inviscid velocity/Cp field on a grid, for client-side vector/contour
    rendering. Inviscid only; grid size is capped server-side (see
    app/backend/app/engine.py::_FLOWFIELD_MAX_CELLS)."""
    try:
        return engine.run_flowfield(req)
    except engine.EngineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail=f"flowfield failed: {type(exc).__name__}: {exc}"
        ) from exc
