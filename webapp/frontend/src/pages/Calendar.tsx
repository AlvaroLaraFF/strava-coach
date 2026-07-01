import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useCalendar } from "../api/hooks";
import { Card, ErrorState, Loading } from "../components/ui";
import { num, pace, sessionType, sport, STATE } from "../lib/format";
import type { CalendarDay } from "../api/types";

const MONTHS = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"];
const DOW = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"];

function iso(d: Date): string { return d.toISOString().slice(0, 10); }
function mondayOf(d: Date): Date {
  const x = new Date(d); const day = (x.getUTCDay() + 6) % 7; x.setUTCDate(x.getUTCDate() - day); return x;
}

export default function CalendarPage() {
  const now = new Date();
  const [ym, setYm] = useState({ y: now.getUTCFullYear(), m: now.getUTCMonth() });
  const [selected, setSelected] = useState<CalendarDay | null>(null);
  const nav = useNavigate();

  const { start, end } = useMemo(() => {
    const first = new Date(Date.UTC(ym.y, ym.m, 1));
    const last = new Date(Date.UTC(ym.y, ym.m + 1, 0));
    const gridStart = mondayOf(first);
    const gridEnd = mondayOf(last); gridEnd.setUTCDate(gridEnd.getUTCDate() + 6);
    return { start: iso(gridStart), end: iso(gridEnd) };
  }, [ym]);

  const { data, isLoading, error } = useCalendar(start, end);
  const today = iso(new Date());

  function shift(delta: number) {
    setYm((p) => {
      const d = new Date(Date.UTC(p.y, p.m + delta, 1));
      return { y: d.getUTCFullYear(), m: d.getUTCMonth() };
    });
  }

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
        <h1 className="page-title" style={{ margin: 0 }}>{MONTHS[ym.m]} {ym.y}</h1>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn ghost" onClick={() => shift(-1)}>‹</button>
          <button className="btn ghost" onClick={() => setYm({ y: now.getUTCFullYear(), m: now.getUTCMonth() })}>Hoy</button>
          <button className="btn ghost" onClick={() => shift(1)}>›</button>
        </div>
      </div>

      <div style={{ display: "flex", gap: 16, marginBottom: 14, flexWrap: "wrap" }}>
        {Object.entries(STATE).filter(([k]) => k !== "empty").map(([k, v]) => (
          <span key={k} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: "var(--muted)" }}>
            <span style={{ width: 10, height: 10, borderRadius: "50%", background: v.color }} /> {v.label}
          </span>
        ))}
      </div>

      {isLoading ? <Loading /> : error ? <ErrorState error={error} /> : (
        <>
          <div className="cal-grid" style={{ marginBottom: 8 }}>
            {DOW.map((d) => <div key={d} className="cal-head">{d}</div>)}
          </div>
          <div className="cal-grid">
            {data!.days.map((day) => {
              const st = STATE[day.state] || STATE.empty;
              const inMonth = new Date(day.date + "T00:00:00Z").getUTCMonth() === ym.m;
              const clickable = day.planned.length > 0 || day.executed.length > 0;
              return (
                <div key={day.date}
                  className={`cal-cell ${day.date === today ? "today" : ""} ${clickable ? "cal-clickable" : ""}`}
                  style={{ opacity: inMonth ? 1 : 0.4 }}
                  onClick={() => clickable && setSelected(day)}>
                  <span className="daynum">{Number(day.date.slice(8, 10))}</span>
                  {day.state !== "empty" && <span className="dot" style={{ background: st.color }} />}
                  {day.planned.filter((p) => p.sport_type !== "Rest").map((p) => (
                    <span key={p.id} className="ev" style={{ color: st.color }}>{sessionType(p.session_type)}</span>
                  ))}
                  {day.executed.map((e) => (
                    <span key={e.strava_id} className="ev" style={{ color: "var(--muted)" }}>
                      {num(e.distance_km, 1)}km · {e.avg_pace_str}
                    </span>
                  ))}
                </div>
              );
            })}
          </div>
        </>
      )}

      {selected && <DayDrawer day={selected} onClose={() => setSelected(null)} onAnalyze={(id) => nav(`/activities/${id}`)} />}
    </div>
  );
}

function DayDrawer({ day, onClose, onAnalyze }: { day: CalendarDay; onClose: () => void; onAnalyze: (id: number) => void }) {
  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} />
      <div className="drawer">
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 16 }}>
          <h2 style={{ margin: 0 }}>{day.date}</h2>
          <button className="btn ghost" onClick={onClose}>✕</button>
        </div>

        {day.planned.length > 0 && (
          <Card title="Planificado" style={{ marginBottom: 14 }}>
            {day.planned.map((p) => (
              <div key={p.id} style={{ marginBottom: 10 }}>
                <b>{sessionType(p.session_type)}</b> <span className="muted">· {sport(p.sport_type)}</span>
                {p.description && <p className="muted" style={{ margin: "4px 0", fontSize: 13 }}>{p.description}</p>}
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  {p.hr_min_bpm ? <span className="chip">FC {p.hr_min_bpm}–{p.hr_max_bpm}</span> : null}
                  {p.pace_fast_min_km ? <span className="chip">{pace(p.pace_fast_min_km)}–{pace(p.pace_slow_min_km)}/km</span> : null}
                </div>
                {p.blocks && p.blocks.length > 0 && (
                  <table className="data" style={{ marginTop: 8 }}>
                    <tbody>
                      {p.blocks.map((b, i) => (
                        <tr key={i}><td style={{ textAlign: "left" }}>{b.repeat_count}× {b.block_type}</td>
                          <td>{b.duration_min ? `${b.duration_min}′` : b.distance_km ? `${b.distance_km}km` : ""}</td>
                          <td>{b.hr_min_bpm ? `${b.hr_min_bpm}–${b.hr_max_bpm}` : ""}</td></tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            ))}
          </Card>
        )}

        {day.executed.length > 0 && (
          <Card title="Ejecutado">
            {day.executed.map((e) => (
              <div key={e.strava_id} style={{ marginBottom: 8 }}>
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <b>{e.name}</b><span className="muted">{e.duration_str}</span>
                </div>
                <div className="muted" style={{ fontSize: 13 }}>
                  {num(e.distance_km, 2)} km · {e.avg_pace_str}/km · FC {num(e.avg_hr)}
                </div>
                <button className="btn" style={{ marginTop: 8 }} onClick={() => onAnalyze(e.strava_id)}>Analizar sesión →</button>
              </div>
            ))}
          </Card>
        )}
      </div>
    </>
  );
}
