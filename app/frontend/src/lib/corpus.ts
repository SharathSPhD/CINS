// Client for the pre-computed airfoil corpus (public/corpus.json, generated
// by scripts/gen_corpus.py). One static asset, fetched once and cached in
// module state: 143 sections with decimated coordinates, order-8 CST fit
// (A_upper/A_lower), and summary geometry, so the gallery corpus grid and
// its CST readout never wait on the backend or fire one request per airfoil.

export interface CorpusAirfoil {
  id: string;
  name: string;
  source: "uiuc" | "naca";
  /** Decimated [x, y] outline, closed loop. */
  coords: number[][];
  thickness: number;
  thickness_x: number;
  camber: number;
  camber_x: number;
  /** Order-8 CST fit, 9 coefficients each. */
  A_upper: number[];
  A_lower: number[];
  fit_rms: number;
  le_radius: number;
}

export interface CorpusFile {
  n_fit: number;
  airfoils: CorpusAirfoil[];
}

let cached: Promise<CorpusFile> | null = null;

/** Fetches /corpus.json once per page load and reuses the result thereafter. */
export function loadCorpus(): Promise<CorpusFile> {
  if (!cached) {
    cached = fetch("/corpus.json")
      .then((res) => {
        if (!res.ok) throw new Error(`failed to load corpus.json: ${res.status}`);
        return res.json() as Promise<CorpusFile>;
      })
      .catch((err) => {
        cached = null; // allow retry on next call
        throw err;
      });
  }
  return cached;
}
