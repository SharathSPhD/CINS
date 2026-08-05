// Class-Shape Transformation (CST) math, computed client-side.
//
// zeta(psi) = C(psi) * S(psi) + psi * zeta_T
//   C(psi)  = psi^N1 * (1-psi)^N2                          (class function)
//   S(psi)  = sum_i A_i * K_i * psi^i * (1-psi)^(n-i)       (shape function)
//   K_i     = n! / (i! (n-i)!)                              (Bernstein coefficient)
//
// Dossier default: N1 = 0.5, N2 = 1.0 (rounded leading edge, sharp-ish trailing
// edge before the zeta_T term). Mirrors src/cins/cst/basis.py; kept independent
// (this is app/frontend, not src/cins) so the CST panel never waits on a
// backend round trip to show what the parameterization is doing.

export const CST_N1_DEFAULT = 0.5;
export const CST_N2_DEFAULT = 1.0;

export function factorial(n: number): number {
  let r = 1;
  for (let i = 2; i <= n; i++) r *= i;
  return r;
}

/** Bernstein coefficient K_i = n! / (i! (n-i)!) for a degree-n polynomial basis. */
export function bernsteinK(n: number, i: number): number {
  // Iterative binomial coefficient: avoids factorial overflow for the
  // orders used here (n <= ~20) and is exact for these integer ranges.
  let k = 1;
  const m = Math.min(i, n - i);
  for (let j = 0; j < m; j++) {
    k = (k * (n - j)) / (j + 1);
  }
  return k;
}

/** Class function C(psi) = psi^N1 * (1-psi)^N2. Vanishes at psi=0 and psi=1 for N1,N2>0. */
export function classFunction(psi: number, N1: number = CST_N1_DEFAULT, N2: number = CST_N2_DEFAULT): number {
  return Math.pow(psi, N1) * Math.pow(1 - psi, N2);
}

export interface ShapeFunctionResult {
  /** Per-coefficient Bernstein term A_i * K_i * psi^i * (1-psi)^(n-i). */
  terms: number[];
  /** S(psi) = sum of terms. */
  sum: number;
}

/** Shape function S(psi) and its Bernstein-term decomposition for coefficient vector A. */
export function shapeFunction(psi: number, A: number[]): ShapeFunctionResult {
  const n = A.length - 1;
  const terms = A.map((a, i) => a * bernsteinK(n, i) * Math.pow(psi, i) * Math.pow(1 - psi, n - i));
  const sum = terms.reduce((s, v) => s + v, 0);
  return { terms, sum };
}

/** Full CST surface: zeta(psi) = C(psi) * S(psi) + psi * zeta_T. */
export function cstSurfaceZeta(
  psi: number,
  A: number[],
  zetaT: number = 0,
  N1: number = CST_N1_DEFAULT,
  N2: number = CST_N2_DEFAULT,
): number {
  const C = classFunction(psi, N1, N2);
  const { sum } = shapeFunction(psi, A);
  return C * sum + psi * zetaT;
}

/** Leading-edge radius derived from the round-nose CST coefficient: R_LE = A0^2 / 2. */
export function leRadiusFromA0(A0: number): number {
  return (A0 * A0) / 2;
}

/** Cosine-spaced psi in [0,1]: denser near both the leading and trailing edges. */
export function psiGrid(nPoints: number = 121): number[] {
  const pts: number[] = [];
  for (let i = 0; i < nPoints; i++) {
    const theta = (Math.PI * i) / (nPoints - 1);
    pts.push(0.5 * (1 - Math.cos(theta)));
  }
  return pts;
}

/**
 * Reconstruct a closed-loop airfoil outline from CST coefficients: upper
 * surface from TE to LE, then lower surface from LE to TE (matches the
 * closed-polyline convention AirfoilShape already draws).
 */
export function cstCoords(
  aUpper: number[],
  aLower: number[],
  zetaTUpper: number = 0,
  zetaTLower: number = 0,
  N1: number = CST_N1_DEFAULT,
  N2: number = CST_N2_DEFAULT,
  nPoints: number = 81,
): number[][] {
  const psis = psiGrid(nPoints);
  const upper = psis.map((psi) => [psi, cstSurfaceZeta(psi, aUpper, zetaTUpper, N1, N2)]);
  const lower = psis.map((psi) => [psi, cstSurfaceZeta(psi, aLower, zetaTLower, N1, N2)]);
  return [...upper.slice().reverse(), ...lower.slice(1)];
}

export interface DerivedFromCoeffs {
  le_radius: number;
  max_thickness: number;
  max_thickness_x: number;
  max_camber: number;
  max_camber_x: number;
}

/**
 * Engineering quantities derived purely from CST coefficients (no fit data
 * required): leading-edge radius from A0, and max thickness/camber found by
 * sampling the reconstructed surfaces on a fine psi grid.
 */
export function derivedFromCoeffs(
  aUpper: number[],
  aLower: number[],
  zetaTUpper: number = 0,
  zetaTLower: number = 0,
  N1: number = CST_N1_DEFAULT,
  N2: number = CST_N2_DEFAULT,
): DerivedFromCoeffs {
  const psis = psiGrid(201);
  let maxT = -Infinity;
  let maxTX = 0;
  let maxC = -Infinity;
  let maxCX = 0;
  for (const psi of psis) {
    const zu = cstSurfaceZeta(psi, aUpper, zetaTUpper, N1, N2);
    const zl = cstSurfaceZeta(psi, aLower, zetaTLower, N1, N2);
    const t = zu - zl;
    const c = Math.abs(0.5 * (zu + zl));
    if (t > maxT) {
      maxT = t;
      maxTX = psi;
    }
    if (c > maxC) {
      maxC = c;
      maxCX = psi;
    }
  }
  return {
    le_radius: leRadiusFromA0(aUpper[0]),
    max_thickness: maxT,
    max_thickness_x: maxTX,
    max_camber: maxC,
    max_camber_x: maxCX,
  };
}
