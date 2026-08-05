"""Pre-compute the archived-results payload as one static asset.

The Gallery shows stored results only: an archived T7 run, the T8 panel sweep
and the paper figures. None of it is solved on demand, yet the page fetched it
from the backend, so a cold container on a free tier left the user looking at
"Loading archived results..." for the length of a spin-up. The data never
changes while the app runs, so it is written here and served alongside the
corpus.

The payload is produced by the backend's own ``run_showcase`` rather than
rebuilt independently, so the static asset and ``GET /api/showcase`` cannot
drift apart.

Run:  .venv/bin/python scripts/gen_showcase.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "app" / "backend"))

from app.engine import run_showcase  # noqa: E402

OUT = REPO / "app" / "frontend" / "public" / "showcase.json"


def main() -> int:
    payload = run_showcase()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, separators=(",", ":"))
    OUT.write_text(text)
    panel = payload.get("panel") or []
    figures = payload.get("figures") or []
    print(
        f"wrote {OUT.relative_to(REPO)}: {len(text) / 1024:.0f} KB, "
        f"{len(panel)} panel cells, {len(figures)} figures"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
