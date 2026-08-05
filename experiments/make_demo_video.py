"""Compose the CINS demo video from rendered frames and UI captures.

Produces three deliverables from one source timeline:

``cins-demo-wide.mp4``      1920x1080, for the site, the app and LinkedIn.
``cins-demo-vertical.mp4``  1080x1920, for short-form vertical feeds.
``cins-demo.gif``           800px wide, short loop for social posts.

Inputs are a directory of numbered animation frames (see make_demo_frames.py)
and a directory of user interface screenshots named in playback order. Title
and caption cards are generated here so the video needs no external assets.

Run:  .venv/bin/python experiments/make_demo_video.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import imageio_ffmpeg
import matplotlib.pyplot as plt
from PIL import Image

BG = "#0b1017"
FG = "#e8eef4"
MUTED = "#7d8fa1"
ACCENT = "#38bdf8"
FPS = 30


def ffmpeg() -> str:
    return imageio_ffmpeg.get_ffmpeg_exe()


def card(text: str, subtitle: str, path: Path, size=(1920, 1080), dpi=120) -> None:
    """Render a title or caption card."""
    fig = plt.figure(figsize=(size[0] / dpi, size[1] / dpi), dpi=dpi, facecolor=BG)
    wrapped = text if len(text) < 48 else text
    fig.text(0.5, 0.56, wrapped, color=FG, fontsize=44 if size[0] > size[1] else 34,
             ha="center", va="center", fontweight="bold", wrap=True)
    fig.text(0.5, 0.42, subtitle, color=MUTED, fontsize=20 if size[0] > size[1] else 16,
             ha="center", va="center", wrap=True)
    fig.text(0.5, 0.12, "CINS  ·  CST Inverse Newton Solver", color=ACCENT,
             fontsize=15, ha="center", family="monospace")
    fig.savefig(path, facecolor=BG)
    plt.close(fig)


def fit_canvas(src: Path, dst: Path, size: tuple[int, int]) -> None:
    """Letterbox an image onto a canvas of the requested size."""
    canvas = Image.new("RGB", size, BG)
    img = Image.open(src).convert("RGB")
    scale = min(size[0] / img.width, size[1] / img.height)
    new = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))),
                     Image.LANCZOS)
    canvas.paste(new, ((size[0] - new.width) // 2, (size[1] - new.height) // 2))
    canvas.save(dst)


def build_timeline(anim_dir: Path, ui_dir: Path, work: Path,
                   size: tuple[int, int]) -> int:
    """Assemble the ordered frame sequence for one aspect ratio."""
    work.mkdir(parents=True, exist_ok=True)
    for f in work.glob("*.png"):
        f.unlink()

    idx = 0

    def emit(img: Path, hold: int = 1) -> None:
        nonlocal idx
        for _ in range(hold):
            fit_canvas(img, work / f"v{idx:05d}.png", size)
            idx += 1

    tmp = work / "_cards"
    tmp.mkdir(exist_ok=True)

    c1 = tmp / "c1.png"
    card("Inverse airfoil design as a Newton root-find",
         "Give the solver a pressure distribution. It returns the geometry.",
         c1, size)
    emit(c1, int(2.5 * FPS))

    ui_frames = sorted(ui_dir.glob("*.png")) if ui_dir.exists() else []
    analyze = [p for p in ui_frames if "analyze" in p.name]
    flow = [p for p in ui_frames if "flow" in p.name]
    theater = [p for p in ui_frames if "inverse" in p.name or "theater" in p.name]
    gallery = [p for p in ui_frames if "gallery" in p.name]
    other = [p for p in ui_frames if p not in analyze + flow + theater + gallery]

    if other:
        c = tmp / "c_app.png"
        card("A working application",
             "Analysis, flow fields and inverse design in the browser.", c, size)
        emit(c, int(1.8 * FPS))
        for p in other:
            emit(p, int(2.2 * FPS))

    if analyze:
        c = tmp / "c_analyze.png"
        card("Analysis", "Pressure distribution, boundary layer and CST parameters.", c, size)
        emit(c, int(1.8 * FPS))
        for p in analyze:
            emit(p, int(2.4 * FPS))

    if flow:
        c = tmp / "c_flow.png"
        card("Flow field", "Velocity magnitude, pressure contours and streamlines.", c, size)
        emit(c, int(1.8 * FPS))
        for p in flow:
            emit(p, int(2.4 * FPS))

    c2 = tmp / "c2.png"
    card("The inverse solve, iteration by iteration",
         "Geometry, sampled pressures and the residual, recorded from a real run.",
         c2, size)
    emit(c2, int(2.2 * FPS))

    for p in sorted(anim_dir.glob("f*.png")):
        emit(p, 1)

    if theater:
        c = tmp / "c_theater.png"
        card("The same solve in the application",
             "Every Newton iteration streamed to the browser.", c, size)
        emit(c, int(1.8 * FPS))
        for p in theater:
            emit(p, int(2.4 * FPS))

    if gallery:
        c = tmp / "c_gallery.png"
        card("Archived evidence", "Panel sweeps, convergence records and paper figures.", c, size)
        emit(c, int(1.8 * FPS))
        for p in gallery:
            emit(p, int(2.4 * FPS))

    c3 = tmp / "c3.png"
    card("18 of 18 sections recovered",
         "NACA panel, 3 to 7 Newton iterations, coefficient error at 1e-11.", c3, size)
    emit(c3, int(2.6 * FPS))

    c4 = tmp / "c4.png"
    card("cins-inverse-design.vercel.app",
         "Application, paper and source: github.com/SharathSPhD/CINS", c4, size)
    emit(c4, int(3.0 * FPS))

    shutil.rmtree(tmp, ignore_errors=True)
    return idx


def encode(work: Path, out: Path, size: tuple[int, int]) -> None:
    cmd = [
        ffmpeg(), "-y", "-framerate", str(FPS),
        "-i", str(work / "v%05d.png"),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-vf", f"scale={size[0]}:{size[1]}:flags=lanczos",
        "-crf", "20", "-preset", "medium", "-movflags", "+faststart",
        str(out),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def make_gif(anim_dir: Path, out: Path, width: int = 800, seconds: float = 12.0) -> None:
    """Short looping GIF of the solve animation for social posts."""
    frames = sorted(anim_dir.glob("f*.png"))
    if not frames:
        return
    step = max(1, int(len(frames) / (seconds * 12)))
    sel = frames[::step]
    tmp = out.parent / "_gif"
    tmp.mkdir(parents=True, exist_ok=True)
    for f in tmp.glob("*.png"):
        f.unlink()
    for i, p in enumerate(sel):
        img = Image.open(p).convert("RGB")
        h = int(img.height * width / img.width)
        img.resize((width, h), Image.LANCZOS).save(tmp / f"g{i:04d}.png")
    palette = tmp / "palette.png"
    subprocess.run([ffmpeg(), "-y", "-i", str(tmp / "g%04d.png"),
                    "-vf", "palettegen=stats_mode=diff", str(palette)],
                   check=True, capture_output=True)
    subprocess.run([ffmpeg(), "-y", "-framerate", "12", "-i", str(tmp / "g%04d.png"),
                    "-i", str(palette), "-lavfi", "paletteuse=dither=bayer:bayer_scale=3",
                    "-loop", "0", str(out)], check=True, capture_output=True)
    shutil.rmtree(tmp, ignore_errors=True)


def main(argv: list[str]) -> int:
    root = Path("experiments/results/demo")
    anim = root / "frames"
    ui = root / "ui"
    out_dir = Path(argv[1]) if len(argv) > 1 else Path("site/assets/demo")
    out_dir.mkdir(parents=True, exist_ok=True)

    if not anim.exists() or not any(anim.glob("f*.png")):
        print("no animation frames; run experiments/make_demo_frames.py first")
        return 1

    n = build_timeline(anim, ui, root / "wide", (1920, 1080))
    encode(root / "wide", out_dir / "cins-demo-wide.mp4", (1920, 1080))
    print(f"wide: {n} frames -> {out_dir/'cins-demo-wide.mp4'}")

    anim_v = root / "frames_vertical"
    if not anim_v.exists() or not any(anim_v.glob("f*.png")):
        anim_v = anim  # fall back to letterboxing the wide frames
    n = build_timeline(anim_v, ui, root / "vertical", (1080, 1920))
    encode(root / "vertical", out_dir / "cins-demo-vertical.mp4", (1080, 1920))
    print(f"vertical: {n} frames -> {out_dir/'cins-demo-vertical.mp4'}")

    make_gif(anim, out_dir / "cins-demo.gif")
    print(f"gif -> {out_dir/'cins-demo.gif'}")

    poster = sorted(anim.glob("f*.png"))[len(list(anim.glob("f*.png"))) // 2]
    fit_canvas(poster, out_dir / "poster.jpg", (1920, 1080))
    for p in sorted(out_dir.iterdir()):
        print(f"  {p.name}: {p.stat().st_size/1e6:.2f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
