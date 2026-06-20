// Typed client for the SWMM Flask backend (the real EPA SWMM engine).

const API_BASE = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:5057';

export interface Dong {
  id: string;
  name_ko: string;
  name_en: string;
}

export interface District {
  id: string;
  name_ko: string;
  name_en: string;
  centroid: [number, number];
  blurb: string;
  dongs: Dong[];
}

export interface TopoNode {
  id: string;
  nx: number;
  ny: number;
  xm: number;
  ym: number;
  ground: number;
  invert: number;
  full: number;
  area: number;
  outfall: boolean;
  sub: { area: number; imp: number } | null;
}

export interface TopoLink {
  id: string;
  f: string;
  t: string;
  D: number;
  L: number;
  n: number;
}

export interface Topology {
  id: string;
  title: string;
  nodes: TopoNode[];
  links: TopoLink[];
  marks: { n: string; x: number; y: number }[];
}

export interface FrameNode {
  depth: number;
  flood: number;
  fillRatio: number;
}
export interface FrameLink {
  flow: number;
  fill: number;
}
export interface Frame {
  t: number;
  nodes: FrameNode[];
  links: FrameLink[];
  sys: { inflow: number; outflow: number; flooding: number };
}

export interface SimSummary {
  flood_nodes: number;
  total_flood_m3: number;
  peak_outflow_cms: number;
  peak_depth_m: number;
  mass_balance_error_pct: number;
}

export interface SimResult {
  gu: string;
  dong: string | null;
  rain_mm_h: number;
  duration_min: number;
  node_ids: string[];
  link_ids: string[];
  frames: Frame[];
  summary: SimSummary;
  topology: Topology;
}

async function getJSON<T>(path: string): Promise<T> {
  const r = await fetch(`${API_BASE}${path}`);
  if (!r.ok) throw new Error(`GET ${path} → ${r.status}`);
  return r.json();
}

export async function fetchDistricts(): Promise<District[]> {
  const d = await getJSON<{ districts: District[] }>('/api/districts');
  return d.districts;
}

export async function fetchNetwork(gu: string, dong?: string | null): Promise<Topology> {
  const path = dong ? `/api/network/${gu}/${dong}` : `/api/network/${gu}`;
  return getJSON<Topology>(path);
}

export async function runSimulation(
  gu: string,
  rainMmH: number,
  dong?: string | null,
  durationMin = 45,
): Promise<SimResult> {
  const r = await fetch(`${API_BASE}/api/simulate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ gu, dong: dong || null, rain_mm_h: rainMmH, duration_min: durationMin }),
  });
  if (!r.ok) {
    let msg = `simulate → ${r.status}`;
    try {
      const e = await r.json();
      if (e?.error) msg = e.error;
    } catch {
      /* ignore */
    }
    throw new Error(msg);
  }
  return r.json();
}

export { API_BASE };
