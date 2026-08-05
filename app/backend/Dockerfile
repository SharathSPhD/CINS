# CINS backend — FastAPI shell over the `cins` engine core.
#
# Build context MUST be the repo root (not app/backend/) so this can copy
# src/, vendor/, configs/, and data/airfoils/ alongside the app package:
#
#   docker build -f app/backend/Dockerfile -t cins-backend .
#   docker run -p 7860:7860 -e ALLOWED_ORIGINS=https://your-frontend.example cins-backend
#
# Port 7860 + single worker is the Hugging Face Spaces Docker-SDK convention
# (HF's default health check hits $PORT, default 7860); set PORT to override.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=7860

WORKDIR /app

# System deps for scipy/matplotlib wheels' runtime needs (matplotlib is
# imported by cins.solver.mfoil_adapter with the Agg backend — no X server
# needed, but libgomp is required by scipy's compiled extensions).
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# --- engine core + vendor + config + data (NOT the app package yet, so the
# pip install layer below is cache-friendly across app-only code changes) ---
COPY pyproject.toml README.md ./
COPY src/ src/
COPY vendor/ vendor/
COPY configs/ configs/
COPY data/airfoils/ data/airfoils/

RUN pip install --no-cache-dir -e .

# --- backend app ---
COPY app/backend/requirements.txt app/backend/requirements.txt
RUN pip install --no-cache-dir -r app/backend/requirements.txt

COPY app/backend/app app/backend/app

EXPOSE 7860

# Single worker: app/jobs.py's in-process job store and app/engine.py's
# MFOIL_LOCK are only correct for one uvicorn worker (app/README.md
# "Concurrency"); do not add --workers.
CMD ["sh", "-c", "uvicorn app.main:app --app-dir app/backend --host 0.0.0.0 --port ${PORT}"]
