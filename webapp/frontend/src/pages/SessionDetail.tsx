import { useParams, useNavigate } from "react-router-dom";
import { useActivity, useSessionAnalysis, useStreams } from "../api/hooks";
import { Badge, Card, Empty, ErrorState, Loading, Metric } from "../components/ui";
import { StreamChart } from "../components/charts";
import SessionMap from "../components/SessionMap";
import { dur, num, pace, shortDate, sport } from "../lib/format";

export default function SessionDetail() {
  const { id } = useParams();
  const sid = Number(id);
  const nav = useNavigate();
  const act = useActivity(sid);
  const streams = useStreams(sid);
  const analysis = useSessionAnalysis({ stravaId: sid });

  if (act.isLoading) return <Loading label="Cargando sesión…" />;
  if (act.error) return <ErrorState error={act.error} />;
  const s = act.data?.summary;
  if (!s) return null;

  const latlng = (streams.data?.latlng?.data as [number, number][] | undefined) || [];
  const a = analysis.data || {};

  return (
    <div>
      <button className="btn ghost" style={{ marginBottom: 14 }} onClick={() => nav(-1)}>‹ Volver</button>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 16, flexWrap: "wrap", gap: 8 }}>
        <h1 className="page-title" style={{ margin: 0 }}>{s.name}</h1>
        <span className="muted">{shortDate(s.start_date)} · {sport(s.sport_type)}{s.imported && <span className="chip" style={{ marginLeft: 8 }}>importada</span>}</span>
      </div>

      <div className="grid cols-4" style={{ marginBottom: 16 }}>
        <Card><Metric label="Distancia" value={`${num(s.distance_km, 2)}`} sub="km" /></Card>
        <Card><Metric label="Tiempo" value={dur(s.moving_time_s)} /></Card>
        <Card><Metric label="Ritmo medio" value={s.avg_pace_str} sub="min/km" /></Card>
        <Card><Metric label="FC media" value={num(s.avg_hr)} sub={`máx ${num(s.max_hr)}`} /></Card>
      </div>

      {Array.isArray(a.narrative) && a.narrative.length > 0 && (
        <Card title="Resumen" style={{ marginBottom: 16 }}>
          <ul style={{ margin: 0, paddingLeft: 18, lineHeight: 1.7 }}>
            {a.narrative.map((n: string, i: number) => <li key={i}>{n}</li>)}
          </ul>
        </Card>
      )}

      {latlng.length > 0 && (
        <Card title="Recorrido" style={{ marginBottom: 16 }}><SessionMap latlng={latlng} /></Card>
      )}

      {streams.data && Object.keys(streams.data).length > 0 && (
        <Card title="Ritmo · FC · Altitud" style={{ marginBottom: 16 }}>
          <StreamChart streams={streams.data} />
        </Card>
      )}

      <div className="grid cols-2" style={{ marginBottom: 16 }}>
        {a.hr_drift && <HrDrift drift={a.hr_drift} />}
        {a.plan_comparison && <PlanComparison pc={a.plan_comparison} />}
      </div>

      {Array.isArray(a.splits) && a.splits.length > 0 && (
        <Card title="Parciales por km" style={{ marginBottom: 16 }}><SplitsTable splits={a.splits} /></Card>
      )}

      {a.interval_breakdown?.reps?.length > 0 && (
        <Card title="Series detectadas" style={{ marginBottom: 16 }}>
          <IntervalTable ib={a.interval_breakdown} />
        </Card>
      )}

      {a.similar_sessions && (
        <Card title="Comparación con sesiones similares">
          <SimilarSessions sim={a.similar_sessions} side={a.side_by_side} />
        </Card>
      )}

      {analysis.isLoading && <Loading label="Analizando la sesión…" />}
      {analysis.error && !Array.isArray(a.narrative) && (
        <Card><Empty label="El análisis detallado no está disponible para esta sesión." /></Card>
      )}
    </div>
  );
}

function HrDrift({ drift }: { drift: any }) {
  const pct = drift.drift_pct;
  const color = pct > 5 ? "var(--amber)" : "var(--green)";
  return (
    <Card title="Deriva cardíaca (Pa:Hr)">
      <Metric label="Drift 1ª → 2ª mitad" value={`${num(pct, 1)}%`} color={color}
        sub={`FC ${num(drift.first_half_hr, 0)} → ${num(drift.second_half_hr, 0)} bpm`} />
      {pct > 5 && <p className="muted" style={{ fontSize: 12, marginBottom: 0 }}>Deriva &gt;5%: revisar contexto (calor, arranque frío, terreno, fatiga).</p>}
    </Card>
  );
}

function PlanComparison({ pc }: { pc: any }) {
  const vColor = (v: string) => (v === "inside" ? "var(--green)" : v === "above" ? "var(--red)" : "var(--amber)");
  const vLabel = (v: string) => (v === "inside" ? "dentro" : v === "above" ? "por encima" : "por debajo");
  return (
    <Card title="Plan vs ejecutado">
      <table className="data">
        <tbody>
          <tr><td style={{ textAlign: "left" }}>Duración</td><td>{num(pc.actual_duration_min, 0)} / {num(pc.planned_duration_min, 0)} min</td></tr>
          <tr><td style={{ textAlign: "left" }}>Distancia</td><td>{num(pc.actual_distance_km, 2)} / {num(pc.planned_distance_km, 2)} km</td></tr>
          <tr><td style={{ textAlign: "left" }}>FC ({pc.planned_hr_range?.join("–")})</td>
            <td><Badge label={vLabel(pc.hr_verdict)} color={vColor(pc.hr_verdict)} /></td></tr>
          <tr><td style={{ textAlign: "left" }}>Ritmo</td>
            <td><Badge label={vLabel(pc.pace_verdict)} color={vColor(pc.pace_verdict)} /></td></tr>
        </tbody>
      </table>
    </Card>
  );
}

function SplitsTable({ splits }: { splits: any[] }) {
  const hasGap = splits.some((s) => s.gap_pace);
  const hasCad = splits.some((s) => s.cadence_spm);
  return (
    <table className="data">
      <thead>
        <tr>
          <th>Km</th><th>Ritmo</th>{hasGap && <th>GAP</th>}{hasGap && <th>Pend.</th>}
          <th>FC</th><th>Zona</th><th>Desnivel</th>{hasCad && <th>Cad</th>}
        </tr>
      </thead>
      <tbody>
        {splits.map((s, i) => (
          <tr key={i}>
            <td style={{ textAlign: "left" }}>{s.km}</td>
            <td>{s.pace}</td>
            {hasGap && <td>{s.gap_pace ?? "–"}</td>}
            {hasGap && <td>{s.grade_pct_net != null ? `${num(s.grade_pct_net, 1)}%` : "–"}</td>}
            <td>{num(s.avg_hr)}</td>
            <td>{s.zone || "–"}</td>
            <td>{num(s.elevation_m, 0)} m</td>
            {hasCad && <td>{num(s.cadence_spm, 0)}</td>}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function IntervalTable({ ib }: { ib: any }) {
  return (
    <table className="data">
      <thead><tr><th>#</th><th>Dur</th><th>Dist</th><th>Ritmo</th><th>FC med</th><th>FC pico</th><th>Cad</th></tr></thead>
      <tbody>
        {ib.reps.map((r: any, i: number) => (
          <tr key={i}>
            <td style={{ textAlign: "left" }}>{r.rep_num ?? i + 1}</td>
            <td>{r.duration_str ?? "–"}</td>
            <td>{r.distance_m ? `${num(r.distance_m, 0)} m` : "–"}</td>
            <td>{r.pace ?? "–"}</td>
            <td>{num(r.avg_hr, 0)}</td>
            <td>{num(r.max_hr, 0)}{r.hr_peak_verdict === "reached" ? " ✓" : ""}</td>
            <td>{num(r.avg_cadence, 0)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function SimilarSessions({ sim, side }: { sim: any; side: any }) {
  return (
    <div>
      <p style={{ marginTop: 0 }}>
        Mediana de {sim.n_similar} sesiones similares ({num(sim.distance_band_km?.[0], 1)}–{num(sim.distance_band_km?.[1], 1)} km):
        <b> {sim.median_pace_str}/km</b>. Esta sesión: {sim.delta_pace_sec_km > 0 ? "+" : ""}{num(sim.delta_pace_sec_km, 0)} s/km,
        FC {sim.delta_hr > 0 ? "+" : ""}{num(sim.delta_hr, 1)} bpm.
      </p>
      {side?.headline && (
        <p className="muted" style={{ fontSize: 13, marginBottom: 0 }}>
          vs misma ruta {shortDate(side.headline.other_date)} ({side.headline.match_age_days} d):
          {" "}{side.headline.delta_pace_sec_km > 0 ? "+" : ""}{num(side.headline.delta_pace_sec_km, 0)} s/km,
          FC {side.headline.delta_hr > 0 ? "+" : ""}{num(side.headline.delta_hr, 1)} bpm.
        </p>
      )}
    </div>
  );
}
