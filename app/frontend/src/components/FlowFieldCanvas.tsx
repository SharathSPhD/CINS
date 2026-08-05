"use client";

// Canvas rendering for the Flow Field view (item 3 of the app rich-features
// brief). Canvas (not SVG) is explicitly called out as fine here — a
// per-pixel heatmap plus ~25 streamlines redrawn on every alpha change is
// exactly the workload SVG struggles with (thousands of DOM nodes) and
// canvas is built for.
//
// Everything below — the color ramp, the bilinear grid sampler, and the RK2
// streamline integrator — is hand-rolled client-side (no plotting/vector-
// field library), consistent with the rest of the app's "own the rendering"
// approach (see CpChart.tsx's rationale).

import { useEffect, useRef } from "react";
import type { FlowFieldResponse } from "@/lib/api";

interface FlowFieldCanvasProps {
  field: FlowFieldResponse;
  colorBy: "speed" | "cp";
  showStreamlines: boolean;
  width?: number;
  height?: number;
}

const MARGIN = 24;
const N_SEEDS = 25;
const N_STEPS = 400;

function viridis(t: number): [number, number, number] {
  // A small hand-picked control-point ramp approximating viridis (dark
  // purple -> teal -> green -> yellow), linearly interpolated. Good enough
  // for a relative-magnitude heatmap; not a perceptually-exact viridis.
  const stops: [number, [number, number, number]][] = [
    [0.0, [68, 1, 84]],
    [0.25, [59, 82, 139]],
    [0.5, [33, 145, 140]],
    [0.75, [94, 201, 98]],
    [1.0, [253, 231, 37]],
  ];
  const c = Math.min(1, Math.max(0, t));
  for (let i = 0; i < stops.length - 1; i++) {
    const [t0, c0] = stops[i];
    const [t1, c1] = stops[i + 1];
    if (c >= t0 && c <= t1) {
      const f = (c - t0) / (t1 - t0 || 1);
      return [
        Math.round(c0[0] + f * (c1[0] - c0[0])),
        Math.round(c0[1] + f * (c1[1] - c0[1])),
        Math.round(c0[2] + f * (c1[2] - c0[2])),
      ];
    }
  }
  return stops[stops.length - 1][1];
}

function makeSampler(field: FlowFieldResponse, key: "u" | "v" | "speed" | "cp") {
  const { x, y } = field;
  const nx = x.length;
  const ny = y.length;
  const dx = (x[nx - 1] - x[0]) / (nx - 1 || 1);
  const dy = (y[ny - 1] - y[0]) / (ny - 1 || 1);
  const grid = field[key];
  return (px: number, py: number): number | null => {
    const fi = (px - x[0]) / dx;
    const fj = (py - y[0]) / dy;
    const i0 = Math.floor(fi);
    const j0 = Math.floor(fj);
    if (i0 < 0 || j0 < 0 || i0 >= nx - 1 || j0 >= ny - 1) return null;
    const v00 = grid[j0][i0];
    const v10 = grid[j0][i0 + 1];
    const v01 = grid[j0 + 1][i0];
    const v11 = grid[j0 + 1][i0 + 1];
    if (v00 == null || v10 == null || v01 == null || v11 == null) return null;
    const tx = fi - i0;
    const ty = fj - j0;
    const top = v00 + (v10 - v00) * tx;
    const bot = v01 + (v11 - v01) * tx;
    return top + (bot - top) * ty;
  };
}

export default function FlowFieldCanvas({
  field,
  colorBy,
  showStreamlines,
  width = 720,
  height = 440,
}: FlowFieldCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const dpr = typeof window !== "undefined" ? window.devicePixelRatio || 1 : 1;
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);

    const { x, y } = field;
    const xMin = x[0], xMax = x[x.length - 1];
    const yMin = y[0], yMax = y[y.length - 1];
    const innerW = width - 2 * MARGIN;
    const innerH = height - 2 * MARGIN;
    const sx = (xx: number) => MARGIN + ((xx - xMin) / (xMax - xMin)) * innerW;
    const sy = (yy: number) => height - MARGIN - ((yy - yMin) / (yMax - yMin)) * innerH;

    // --- heatmap: draw the low-res field grid onto an offscreen canvas,
    // then scale it up with drawImage (nearest-neighbor) ---
    const field2d = colorBy === "speed" ? field.speed : field.cp;
    let vmin = Infinity, vmax = -Infinity;
    for (const row of field2d) for (const v of row) if (v != null) { if (v < vmin) vmin = v; if (v > vmax) vmax = v; }
    if (!isFinite(vmin)) { vmin = 0; vmax = 1; }
    const span = vmax - vmin || 1;

    const off = document.createElement("canvas");
    off.width = field.nx;
    off.height = field.ny;
    const offCtx = off.getContext("2d")!;
    const img = offCtx.createImageData(field.nx, field.ny);
    for (let j = 0; j < field.ny; j++) {
      for (let i = 0; i < field.nx; i++) {
        // Image row 0 renders at the TOP of the drawImage target, but data row
        // j=0 is y_min (bottom) — write rows flipped so the heatmap matches the
        // silhouette's y-up world transform. (Bug: suction side rendered below
        // the airfoil at positive alpha; backend data verified correct.)
        const idx = ((field.ny - 1 - j) * field.nx + i) * 4;
        const v = field2d[j][i];
        if (v == null) {
          img.data[idx + 3] = 0; // transparent inside the body
          continue;
        }
        const t = colorBy === "cp" ? 1 - (v - vmin) / span : (v - vmin) / span; // invert Cp so suction (low Cp) reads "hot"
        const [r, g, b] = viridis(t);
        img.data[idx] = r;
        img.data[idx + 1] = g;
        img.data[idx + 2] = b;
        img.data[idx + 3] = 235;
      }
    }
    offCtx.putImageData(img, 0, 0);
    ctx.imageSmoothingEnabled = true;
    ctx.drawImage(off, sx(xMin), sy(yMax), innerW, innerH);

    // --- streamlines: RK2 (midpoint) advection through (u, v), seeded on a
    // vertical line upstream of the airfoil ---
    if (showStreamlines) {
      const uAt = makeSampler(field, "u");
      const vAt = makeSampler(field, "v");
      const seedX = xMin + 0.03 * (xMax - xMin);
      const yLo = yMin + 0.05 * (yMax - yMin);
      const yHi = yMax - 0.05 * (yMax - yMin);
      const dt = ((xMax - xMin) / field.nx) * 0.6;

      ctx.strokeStyle = "rgba(255,255,255,0.85)";
      ctx.lineWidth = 1.1;
      for (let s = 0; s < N_SEEDS; s++) {
        const y0 = yLo + (s / (N_SEEDS - 1)) * (yHi - yLo);
        let px = seedX, py = y0;
        ctx.beginPath();
        ctx.moveTo(sx(px), sy(py));
        for (let step = 0; step < N_STEPS; step++) {
          const u1 = uAt(px, py), v1 = vAt(px, py);
          if (u1 == null || v1 == null) break;
          const midX = px + (dt / 2) * u1, midY = py + (dt / 2) * v1;
          const u2 = uAt(midX, midY), v2 = vAt(midX, midY);
          if (u2 == null || v2 == null) break;
          px += dt * u2;
          py += dt * v2;
          if (px < xMin || px > xMax || py < yMin || py > yMax) break;
          ctx.lineTo(sx(px), sy(py));
        }
        ctx.stroke();
      }
    }

    // --- airfoil silhouette ---
    ctx.fillStyle = "#111827";
    ctx.strokeStyle = "#e5e7eb";
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    field.airfoil.forEach(([ax, ay], i) => {
      const px = sx(ax), py = sy(ay);
      if (i === 0) ctx.moveTo(px, py);
      else ctx.lineTo(px, py);
    });
    ctx.closePath();
    ctx.fill();
    ctx.stroke();

    // --- axes frame ---
    ctx.strokeStyle = "rgba(148,163,184,0.6)";
    ctx.lineWidth = 1;
    ctx.strokeRect(MARGIN, MARGIN, innerW, innerH);
  }, [field, colorBy, showStreamlines, width, height]);

  return (
    <canvas
      ref={canvasRef}
      style={{ width: "100%", height: "auto", aspectRatio: `${width} / ${height}` }}
      role="img"
      aria-label={`Flow field around the airfoil, colored by ${colorBy === "speed" ? "velocity magnitude" : "pressure coefficient"}`}
    />
  );
}
