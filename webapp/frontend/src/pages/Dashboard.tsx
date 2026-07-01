import { useNavigate } from "react-router-dom";
import { useDashboard } from "../api/hooks";
import { Badge, Card, ErrorState, Loading, Metric } from "../components/ui";
import { dur, num, pace, sessionType, shortDate, sport, VERDICT } from "../lib/format";
import type { ActivityBrief, PlannedSession } from "../api/types";

export default function Dashboard() {
  const { data, isLoading, error } = useDashboard();
  const nav = useNavigate();
  if (isLoading) return <Loading label="Cargando panel…" />;
  if (error) return <ErrorState error={error} />;
  if (!data) return null;

  const s = data.snapshot || {};
  const v = VERDICT[data.tsb_verdict] || VERDICT.unknown;

  return (
    <div>
      <h1 className="page-title">Panel</h1>

      <div className="grid cols-4" style={{ marginBottom: 16 }}>
        <Card>
          <Metric label="Forma (TSB)" value={num(s.tsb, 1)} color={v.color}
            sub={<Badge label={v.label} color={v.color} />} />
        </Card>
        <Card><Metric label="Fitness (CTL)" value={num(s.ctl, 1)} sub="carga crónica" /></Card>
        <Card><Metric label="Fatiga (ATL)" value={num(s.atl, 1)} sub="carga aguda" /></Card>
        <Card><Metric label="ACWR" value={num(s.acwr, 2)} sub="agudo / crónico" /></Card>
      </div>

      <div className="grid cols-4" style={{ marginBottom: 16 }}>
        <Card><Metric label="VDOT" value={num(s.vdot, 1)} /></Card>
        <Card><Metric label="Ritmo umbral" value={`${pace(s.threshold_pace_min_km)}`} sub="min/km" /></Card>
        <Card><Metric label="FC máx" value={num(s.hr_max_bpm)} sub="bpm" /></Card>
        <Card><Metric label="FC reposo" value={num(s.hr_rest_bpm)} sub="bpm" /></Card>
      </div>

      <div className="grid cols-2">
        <NextSession session={data.next_session} onOpen={(d) => nav(`/calendar`)} />
        <Card title="Últimas sesiones">
          {data.recent.length === 0 ? <span className="muted">Sin actividades.</span> : (
            <table className="data">
              <thead><tr><th>Fecha</th><th>Sesión</th><th>Dist</th><th>Ritmo</th><th>FC</th></tr></thead>
              <tbody>
                {data.recent.map((a: ActivityBrief) => (
                  <tr key={a.strava_id} className="row-link" onClick={() => nav(`/activities/${a.strava_id}`)}>
                    <td>{shortDate(a.start_date)}</td>
                    <td style={{ textAlign: "left" }}>{sport(a.sport_type)}{a.imported && <span className="chip" style={{ marginLeft: 6 }}>import</span>}</td>
                    <td>{num(a.distance_km, 2)} km</td>
                    <td>{a.avg_pace_str}</td>
                    <td>{num(a.avg_hr)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>
    </div>
  );
}

function NextSession({ session, onOpen }: { session: PlannedSession | null; onOpen: (d: string) => void }) {
  return (
    <Card title="Próxima sesión">
      {!session ? <span className="muted">No hay sesiones planificadas próximas.</span> : (
        <div>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 8 }}>
            <span style={{ fontSize: 20, fontWeight: 800 }}>{sessionType(session.session_type)}</span>
            <span className="muted">{shortDate(session.plan_date)}</span>
          </div>
          {session.description && <p className="muted" style={{ marginTop: 0, fontSize: 13 }}>{session.description}</p>}
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {session.duration_min ? <span className="chip">{session.duration_min} min</span> : null}
            {session.distance_km ? <span className="chip">{session.distance_km} km</span> : null}
            {session.hr_min_bpm ? <span className="chip">FC {session.hr_min_bpm}–{session.hr_max_bpm}</span> : null}
            {session.pace_fast_min_km ? <span className="chip">{pace(session.pace_fast_min_km)}–{pace(session.pace_slow_min_km)}/km</span> : null}
          </div>
          {session.blocks && session.blocks.length > 0 && (
            <table className="data" style={{ marginTop: 12 }}>
              <thead><tr><th>Bloque</th><th>×</th><th>Dur</th><th>FC</th><th>Ritmo</th></tr></thead>
              <tbody>
                {session.blocks.map((b, i) => (
                  <tr key={i}>
                    <td style={{ textAlign: "left" }}>{b.block_type}</td>
                    <td>{b.repeat_count}</td>
                    <td>{b.duration_min ? `${b.duration_min}′` : b.distance_km ? `${b.distance_km}km` : "–"}</td>
                    <td>{b.hr_min_bpm ? `${b.hr_min_bpm}–${b.hr_max_bpm}` : "–"}</td>
                    <td>{b.pace_fast_min_km ? `${pace(b.pace_fast_min_km)}–${pace(b.pace_slow_min_km)}` : "–"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </Card>
  );
}
