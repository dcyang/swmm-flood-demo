import { useCallback, useEffect, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import {
  IonBackButton,
  IonButton,
  IonButtons,
  IonContent,
  IonHeader,
  IonPage,
  IonRange,
  IonSegment,
  IonSegmentButton,
  IonSpinner,
  IonTitle,
  IonToolbar,
} from '@ionic/react';

import {
  fetchDistricts,
  fetchNetwork,
  runSimulation,
  type District,
  type SimResult,
  type Topology,
} from '../services/swmmApi';
import { drawMiniChart, drawNetwork } from '../sim/render';

const PRESETS = [
  { v: 30, label: '약한 비 30' },
  { v: 70, label: '호우 70' },
  { v: 110, label: '집중호우 110' },
  { v: 160, label: '극한강우 160' },
];
const DURATION_MIN = 45;

export default function DistrictDetail() {
  const { gu } = useParams<{ gu: string }>();

  const [district, setDistrict] = useState<District | null>(null);
  const [dong, setDong] = useState<string>('__all__');
  const [rain, setRain] = useState(60);
  const [speed, setSpeed] = useState(6);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [playing, setPlaying] = useState(false);
  const [hasResult, setHasResult] = useState(false);
  const [stats, setStats] = useState({
    t: 0, inflow: 0, outflow: 0, floodNodes: 0, floodVol: 0,
  });
  const [summary, setSummary] = useState<SimResult['summary'] | null>(null);

  // refs driven by the animation loop (avoid re-render per frame)
  const netRef = useRef<HTMLCanvasElement>(null);
  const hyetoRef = useRef<HTMLCanvasElement>(null);
  const hydroRef = useRef<HTMLCanvasElement>(null);
  const topoRef = useRef<Topology | null>(null);
  const resultRef = useRef<SimResult | null>(null);
  const cumFloodRef = useRef<number[]>([]);
  const playheadRef = useRef(0);
  const playingRef = useRef(false);
  const rainRef = useRef(rain);
  const speedRef = useRef(speed);
  const lastTsRef = useRef(0);

  rainRef.current = rain;
  speedRef.current = speed;
  playingRef.current = playing;

  // load district metadata (for dong segment + title)
  useEffect(() => {
    fetchDistricts()
      .then((ds) => setDistrict(ds.find((d) => d.id === gu) || null))
      .catch((e) => setError(String(e.message || e)));
  }, [gu]);

  const loadNetwork = useCallback(async () => {
    setPlaying(false);
    setHasResult(false);
    setSummary(null);
    resultRef.current = null;
    playheadRef.current = 0;
    setStats({ t: 0, inflow: 0, outflow: 0, floodNodes: 0, floodVol: 0 });
    try {
      const d = dong === '__all__' ? null : dong;
      topoRef.current = await fetchNetwork(gu, d);
    } catch (e: any) {
      setError(String(e.message || e));
    }
  }, [gu, dong]);

  useEffect(() => {
    void loadNetwork();
  }, [loadNetwork]);

  // continuous render loop: animates during playback, idle-draws otherwise
  useEffect(() => {
    let raf = 0;
    const loop = (ts: number) => {
      raf = requestAnimationFrame(loop);
      const dt = Math.min(0.05, (ts - lastTsRef.current) / 1000 || 0.016);
      lastTsRef.current = ts;
      const cv = netRef.current;
      if (!cv) return;
      const topo = topoRef.current;
      if (!topo) return;

      const result = resultRef.current;
      let frame = null;
      if (result && result.frames.length) {
        if (playingRef.current) {
          playheadRef.current += dt * speedRef.current;
          if (playheadRef.current >= result.frames.length - 1) {
            playheadRef.current = result.frames.length - 1;
            playingRef.current = false;
            setPlaying(false);
          }
        }
        const idx = Math.max(0, Math.min(result.frames.length - 1, Math.floor(playheadRef.current)));
        frame = result.frames[idx];
        updateReadouts(result, idx);
      }

      drawNetwork(cv, topo, result?.node_ids ?? [], result?.link_ids ?? [], frame, {
        rain: rainRef.current,
        running: playingRef.current,
        time: ts / 1000,
      });

      // charts up to current playhead
      if (result) {
        const idx = Math.floor(playheadRef.current);
        const hydro = result.frames.slice(0, idx + 1).map((f) => f.sys.outflow);
        const hyeto = result.frames
          .slice(0, idx + 1)
          .map((f) => (f.t < result.duration_min * 60 ? result.rain_mm_h : 0));
        if (hydroRef.current) drawMiniChart(hydroRef.current, hydro, '#6ee7b7', '방류 (m³/s)', 2);
        if (hyetoRef.current) drawMiniChart(hyetoRef.current, hyeto, '#37c0ff', '강우 (mm/h)', 180);
      } else if (hydroRef.current && hyetoRef.current) {
        drawMiniChart(hydroRef.current, [], '#6ee7b7', '방류 (m³/s)', 2);
        drawMiniChart(hyetoRef.current, [], '#37c0ff', '강우 (mm/h)', 180);
      }
    };
    raf = requestAnimationFrame(loop);
    const onResize = () => { lastTsRef.current = performance.now(); };
    window.addEventListener('resize', onResize);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener('resize', onResize);
    };
  }, []);

  let lastReadoutIdx = -1;
  function updateReadouts(result: SimResult, idx: number) {
    if (idx === lastReadoutIdx) return;
    lastReadoutIdx = idx;
    const f = result.frames[idx];
    const floodNodes = f.nodes.filter((n) => n.flood > 0.003).length;
    setStats({
      t: f.t,
      inflow: f.sys.inflow,
      outflow: f.sys.outflow,
      floodNodes,
      floodVol: cumFloodRef.current[idx] ?? 0,
    });
  }

  async function onRun() {
    setError(null);
    setLoading(true);
    setPlaying(false);
    try {
      const d = dong === '__all__' ? null : dong;
      const res = await runSimulation(gu, rain, d, DURATION_MIN);
      // precompute cumulative flooding volume per frame
      const cum: number[] = [];
      let acc = 0;
      let prevT = 0;
      res.frames.forEach((f, i) => {
        acc += f.sys.flooding * (f.t - prevT);
        prevT = f.t;
        cum[i] = acc;
      });
      cumFloodRef.current = cum;
      resultRef.current = res;
      topoRef.current = res.topology;
      playheadRef.current = 0;
      setSummary(res.summary);
      setHasResult(true);
      setPlaying(true);
    } catch (e: any) {
      setError(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }

  function onReset() {
    setPlaying(false);
    playheadRef.current = 0;
    setStats({ t: 0, inflow: 0, outflow: 0, floodNodes: 0, floodVol: 0 });
  }

  const clock = fmtClock(stats.t);
  const title = district ? `${district.name_ko}` : gu;

  return (
    <IonPage>
      <IonHeader>
        <IonToolbar>
          <IonButtons slot="start">
            <IonBackButton defaultHref="/districts" />
          </IonButtons>
          <IonTitle>{title} 침수 시뮬레이션</IonTitle>
        </IonToolbar>
      </IonHeader>
      <IonContent>
        <div style={{ padding: 12, display: 'flex', flexDirection: 'column', gap: 12 }}>
          {/* dong selector */}
          {district && district.dongs.length > 0 && (
            <IonSegment
              scrollable
              value={dong}
              onIonChange={(e) => setDong(String(e.detail.value))}
            >
              <IonSegmentButton value="__all__">구 전체</IonSegmentButton>
              {district.dongs.map((dn) => (
                <IonSegmentButton key={dn.id} value={dn.id}>
                  {dn.name_ko}
                </IonSegmentButton>
              ))}
            </IonSegment>
          )}

          {/* network canvas */}
          <div style={panel}>
            <div style={{ position: 'relative' }}>
              <canvas
                ref={netRef}
                style={{ width: '100%', height: '44vh', display: 'block', borderRadius: 10 }}
              />
              <span style={clockPill}>{clock}</span>
            </div>
          </div>

          {/* legend */}
          <div style={{ ...legend }}>
            <Legend c="#2b6cff" t="관거 여유" />
            <Legend c="#ffb454" t="만관 임박" />
            <Legend c="#ff5470" t="과부하·월류" />
            <Legend c="#6ee7b7" t="소유역 유출" />
          </div>

          {/* rainfall controls */}
          <div style={panel}>
            <h2 style={h2}>강우 입력 (Rainfall)</h2>
            <IonRange
              min={0}
              max={180}
              step={5}
              value={rain}
              onIonInput={(e) => setRain(Number(e.detail.value))}
              pin
            />
            <div style={{ textAlign: 'right', fontSize: 13, color: 'var(--app-muted)' }}>
              {rain} mm/h
            </div>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 6 }}>
              {PRESETS.map((p) => (
                <button key={p.v} style={chip(rain === p.v)} onClick={() => setRain(p.v)}>
                  {p.label}
                </button>
              ))}
            </div>

            <h2 style={{ ...h2, marginTop: 14 }}>재생 속도</h2>
            <IonRange
              min={1}
              max={20}
              step={1}
              value={speed}
              onIonInput={(e) => setSpeed(Number(e.detail.value))}
              pin
            />

            <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
              <IonButton expand="block" style={{ flex: 1 }} disabled={loading} onClick={onRun}>
                {loading ? <IonSpinner name="dots" /> : hasResult ? '▶ 다시 실행' : '▶ 시뮬레이션 실행'}
              </IonButton>
              {hasResult && (
                <IonButton
                  fill="outline"
                  onClick={() => setPlaying((p) => !p)}
                  style={{ width: 96 }}
                >
                  {playing ? '⏸ 정지' : '▶ 재생'}
                </IonButton>
              )}
              <IonButton color="medium" fill="outline" onClick={onReset} style={{ width: 72 }}>
                ⟲
              </IonButton>
            </div>
            {error && (
              <p style={{ color: 'var(--app-flood)', fontSize: 12, marginBottom: 0 }}>{error}</p>
            )}
          </div>

          {/* live stats */}
          <div style={panel}>
            <h2 style={h2}>시스템 상태 (Live)</h2>
            <Stat k="총 유입 (소유역 유출)" v={`${stats.inflow.toFixed(2)} m³/s`} />
            <Stat k="방류구 유출량" v={`${stats.outflow.toFixed(2)} m³/s`} />
            <Stat
              k="침수(월류) 노드"
              v={`${stats.floodNodes} 개`}
              flood={stats.floodNodes > 0}
            />
            <Stat
              k="누적 침수량"
              v={`${stats.floodVol.toFixed(0)} m³`}
              flood={stats.floodVol > 1}
            />
          </div>

          {/* charts */}
          <div style={panel}>
            <h2 style={h2}>강우주상도 / 방류 수문곡선</h2>
            <canvas ref={hyetoRef} style={miniChartStyle} />
            <canvas ref={hydroRef} style={{ ...miniChartStyle, marginTop: 6 }} />
          </div>

          {/* result summary (real engine) */}
          {summary && (
            <div style={panel}>
              <h2 style={h2}>SWMM 결과 요약 (실물 엔진)</h2>
              <Stat k="침수 발생 노드" v={`${summary.flood_nodes} 개`} flood={summary.flood_nodes > 0} />
              <Stat k="총 침수량" v={`${summary.total_flood_m3.toLocaleString()} m³`} />
              <Stat k="최대 방류량" v={`${summary.peak_outflow_cms.toFixed(2)} m³/s`} />
              <Stat k="질량보존 오차" v={`${summary.mass_balance_error_pct.toFixed(3)} %`} />
            </div>
          )}
        </div>
      </IonContent>
    </IonPage>
  );
}

/* ---- small presentational helpers ---- */
const panel: React.CSSProperties = {
  background: 'linear-gradient(180deg,var(--app-panel) 0%,var(--app-panel2) 100%)',
  border: '1px solid var(--app-line)',
  borderRadius: 14,
  padding: 12,
};
const h2: React.CSSProperties = {
  fontSize: 12,
  textTransform: 'uppercase',
  letterSpacing: 1.2,
  color: 'var(--app-muted)',
  margin: '0 0 8px',
};
const legend: React.CSSProperties = {
  display: 'flex',
  gap: 14,
  flexWrap: 'wrap',
  fontSize: 11,
  color: 'var(--app-muted)',
  padding: '0 4px',
};
const clockPill: React.CSSProperties = {
  position: 'absolute',
  top: 8,
  right: 10,
  fontSize: 12,
  color: 'var(--app-accent2)',
  background: '#0e2a22',
  border: '1px solid #1c4a3a',
  borderRadius: 20,
  padding: '3px 9px',
  fontVariantNumeric: 'tabular-nums',
};
const miniChartStyle: React.CSSProperties = {
  width: '100%',
  height: 74,
  border: '1px solid var(--app-line)',
  borderRadius: 8,
  background: '#0a1322',
  display: 'block',
};
function chip(active: boolean): React.CSSProperties {
  return {
    cursor: 'pointer',
    border: `1px solid ${active ? 'var(--ion-color-primary)' : 'var(--app-line)'}`,
    background: active ? '#13314a' : '#15233a',
    color: 'var(--ion-text-color)',
    padding: '7px 10px',
    borderRadius: 10,
    fontSize: 12,
  };
}

function Legend({ c, t }: { c: string; t: string }) {
  return (
    <span>
      <i
        style={{
          display: 'inline-block',
          width: 11,
          height: 11,
          borderRadius: 3,
          background: c,
          marginRight: 5,
          verticalAlign: -1,
        }}
      />
      {t}
    </span>
  );
}

function Stat({ k, v, flood }: { k: string; v: string; flood?: boolean }) {
  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'baseline',
        padding: '7px 0',
        borderBottom: '1px dashed var(--app-line)',
      }}
    >
      <span style={{ fontSize: 12, color: 'var(--app-muted)' }}>{k}</span>
      <span
        style={{
          fontSize: 16,
          fontWeight: 600,
          fontVariantNumeric: 'tabular-nums',
          color: flood ? 'var(--app-flood)' : 'var(--app-accent2)',
        }}
      >
        {v}
      </span>
    </div>
  );
}

function fmtClock(sec: number): string {
  const s = Math.floor(sec);
  const hh = String(Math.floor(s / 3600)).padStart(2, '0');
  const mm = String(Math.floor(s / 60) % 60).padStart(2, '0');
  const ss = String(s % 60).padStart(2, '0');
  return `${hh}:${mm}:${ss}`;
}
