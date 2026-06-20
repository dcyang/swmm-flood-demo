// Canvas renderer + playback for SWMM results.
//
// This ports the visual language of gangnam.html (pipes colored by fill, flow
// particles, manhole water levels, flood pulses, rain) but instead of computing
// physics it draws a single server-provided Frame over the network Topology.

import type { Frame, Topology } from '../services/swmmApi';

type RGB = [number, number, number];
const C_LOW: RGB = [43, 108, 255];
const C_MID: RGB = [255, 180, 84];
const C_HI: RGB = [255, 84, 112];
const PAD = 26;

function lerp(a: RGB, b: RGB, t: number): string {
  return `rgb(${a.map((v, i) => Math.round(v + (b[i] - v) * t)).join(',')})`;
}

function fillColor(ratio: number): string {
  return ratio < 0.7 ? lerp(C_LOW, C_MID, ratio / 0.7) : lerp(C_MID, C_HI, (ratio - 0.7) / 0.3);
}

export interface RenderOpts {
  rain: number; // mm/h, for rain animation + intensity
  running: boolean;
  time: number; // seconds, drives animation phase
}

/** Fit the canvas backing store to its CSS box at device pixel ratio. */
export function fitCanvas(cv: HTMLCanvasElement): { w: number; h: number } {
  const r = cv.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  const w = Math.max(1, Math.floor(r.width));
  const h = Math.max(1, Math.floor(r.height));
  if (cv.width !== w * dpr || cv.height !== h * dpr) {
    cv.width = w * dpr;
    cv.height = h * dpr;
  }
  const ctx = cv.getContext('2d')!;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { w, h };
}

export function drawNetwork(
  cv: HTMLCanvasElement,
  topo: Topology,
  nodeIds: string[],
  linkIds: string[],
  frame: Frame | null,
  opts: RenderOpts,
): void {
  const cx = cv.getContext('2d')!;
  const { w, h } = fitCanvas(cv);
  cx.clearRect(0, 0, w, h);

  const pos = (nx: number, ny: number) => ({
    x: PAD + nx * (w - 2 * PAD),
    y: PAD + ny * (h - 2 * PAD),
  });
  const nodeById = new Map(topo.nodes.map((n) => [n.id, n]));
  const fNode = new Map<string, Frame['nodes'][number]>();
  const fLink = new Map<string, Frame['links'][number]>();
  if (frame) {
    nodeIds.forEach((id, i) => fNode.set(id, frame.nodes[i]));
    linkIds.forEach((id, i) => fLink.set(id, frame.links[i]));
  }

  // background grid
  cx.strokeStyle = '#13203a';
  cx.lineWidth = 1;
  for (let gx = 0; gx < w; gx += 40) {
    cx.beginPath();
    cx.moveTo(gx, 0);
    cx.lineTo(gx, h);
    cx.stroke();
  }
  for (let gy = 0; gy < h; gy += 40) {
    cx.beginPath();
    cx.moveTo(0, gy);
    cx.lineTo(w, gy);
    cx.stroke();
  }

  // subcatchment wetness halo
  for (const n of topo.nodes) {
    if (!n.sub) continue;
    const p = pos(n.nx, n.ny);
    const fr = fNode.get(n.id)?.fillRatio ?? 0;
    cx.fillStyle = `rgba(110,231,183,${0.04 + 0.16 * fr})`;
    cx.beginPath();
    cx.arc(p.x, p.y, 22, 0, 7);
    cx.fill();
  }

  // conduits
  for (const lk of topo.links) {
    const u = nodeById.get(lk.f);
    const d = nodeById.get(lk.t);
    if (!u || !d) continue;
    const a = pos(u.nx, u.ny);
    const b = pos(d.nx, d.ny);
    const fl = fLink.get(lk.id);
    const fill = fl ? fl.fill : 0;
    cx.strokeStyle = '#0a1322';
    cx.lineWidth = 8 + lk.D * 4;
    cx.lineCap = 'round';
    cx.beginPath();
    cx.moveTo(a.x, a.y);
    cx.lineTo(b.x, b.y);
    cx.stroke();
    cx.strokeStyle = fillColor(Math.min(1, fill));
    cx.lineWidth = 3 + lk.D * 3.4;
    cx.beginPath();
    cx.moveTo(a.x, a.y);
    cx.lineTo(b.x, b.y);
    cx.stroke();
    // flow particle
    const flow = fl?.flow ?? 0;
    if (Math.abs(flow) > 0.002) {
      const t = (opts.time * 0.6) % 1;
      const dir = flow >= 0 ? t : 1 - t;
      const px = a.x + (b.x - a.x) * dir;
      const py = a.y + (b.y - a.y) * dir;
      cx.fillStyle = 'rgba(255,255,255,.85)';
      cx.beginPath();
      cx.arc(px, py, 2.4, 0, 7);
      cx.fill();
    }
  }

  // nodes (manholes / outfalls)
  for (const n of topo.nodes) {
    const p = pos(n.nx, n.ny);
    const rec = fNode.get(n.id);
    const R = n.outfall ? 9 : 7;
    const ratio = n.outfall ? 0 : Math.min(1, rec?.fillRatio ?? 0);
    cx.fillStyle = '#0a1322';
    cx.beginPath();
    cx.arc(p.x, p.y, R + 2, 0, 7);
    cx.fill();
    cx.fillStyle = '#1b2c47';
    cx.beginPath();
    cx.arc(p.x, p.y, R, 0, 7);
    cx.fill();
    const fill = n.outfall ? '#37c0ff' : fillColor(ratio);
    cx.save();
    cx.beginPath();
    cx.arc(p.x, p.y, R, 0, 7);
    cx.clip();
    cx.fillStyle = fill;
    cx.fillRect(p.x - R, p.y + R - 2 * R * ratio, 2 * R, 2 * R * ratio);
    cx.restore();

    const flood = rec?.flood ?? 0;
    if (flood > 0.003) {
      const pulse = 0.5 + 0.5 * Math.sin(opts.time * 6);
      cx.strokeStyle = `rgba(255,84,112,${0.45 + 0.5 * pulse})`;
      cx.lineWidth = 2.5;
      cx.beginPath();
      cx.arc(p.x, p.y, R + 5 + 4 * pulse, 0, 7);
      cx.stroke();
    }
    cx.strokeStyle = n.outfall ? '#37c0ff' : '#9bb4d6';
    cx.lineWidth = 1.4;
    cx.beginPath();
    cx.arc(p.x, p.y, R, 0, 7);
    cx.stroke();
  }

  // landmark labels
  cx.fillStyle = 'rgba(207,224,248,.7)';
  cx.font = '11px sans-serif';
  cx.textAlign = 'center';
  for (const m of topo.marks) {
    const p = pos(m.x, m.y);
    cx.fillText(m.n, p.x, p.y - 12);
  }

  // rain
  if (opts.rain > 0 && opts.running) {
    const drops = Math.round(opts.rain / 7);
    cx.strokeStyle = 'rgba(120,180,255,.35)';
    cx.lineWidth = 1;
    for (let k = 0; k < drops; k++) {
      const rx = (k * 97.13 + opts.time * 120 * (0.5 + opts.rain / 360)) % w;
      const ry = (k * 53.7 + opts.time * 420 * (0.5 + opts.rain / 360)) % h;
      cx.beginPath();
      cx.moveTo(rx, ry);
      cx.lineTo(rx - 2, ry + 8);
      cx.stroke();
    }
  }
}

/** Small line chart (rainfall / outflow), progressive up to `count` samples. */
export function drawMiniChart(
  cv: HTMLCanvasElement,
  data: number[],
  color: string,
  label: string,
  max: number,
): void {
  const x = cv.getContext('2d')!;
  const { w, h } = fitCanvas(cv);
  x.clearRect(0, 0, w, h);
  const mx = Math.max(max, ...data, 0.001);
  const n = data.length;
  const step = w / Math.max(n - 1, 1);
  x.strokeStyle = color;
  x.lineWidth = 2;
  x.beginPath();
  for (let i = 0; i < n; i++) {
    const px = i * step;
    const py = h - 4 - (data[i] / mx) * (h - 12);
    if (i) x.lineTo(px, py);
    else x.moveTo(px, py);
  }
  x.stroke();
  if (n > 1) {
    x.fillStyle = color + '22';
    x.lineTo((n - 1) * step, h);
    x.lineTo(0, h);
    x.closePath();
    x.fill();
  }
  x.fillStyle = '#8fa6c4';
  x.font = '10px sans-serif';
  x.textAlign = 'left';
  x.fillText(label, 6, 12);
}
