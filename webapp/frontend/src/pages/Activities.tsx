import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useActivities } from "../api/hooks";
import { Card, ErrorState, Loading } from "../components/ui";
import { num, shortDate, sport } from "../lib/format";

const RANGES = [{ d: 30, l: "30 d" }, { d: 90, l: "90 d" }, { d: 365, l: "1 año" }, { d: 3650, l: "Todo" }];

export default function Activities() {
  const [days, setDays] = useState(90);
  const { data, isLoading, error } = useActivities(days);
  const nav = useNavigate();

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
        <h1 className="page-title" style={{ margin: 0 }}>Actividades</h1>
        <div className="seg">
          {RANGES.map((r) => (
            <button key={r.d} className={days === r.d ? "active" : ""} onClick={() => setDays(r.d)}>{r.l}</button>
          ))}
        </div>
      </div>
      {isLoading ? <Loading /> : error ? <ErrorState error={error} /> : (
        <Card>
          <table className="data">
            <thead>
              <tr><th>Fecha</th><th>Deporte</th><th>Nombre</th><th>Dist</th><th>Tiempo</th><th>Ritmo</th><th>FC</th><th>Desnivel</th></tr>
            </thead>
            <tbody>
              {data!.activities.map((a) => (
                <tr key={a.strava_id} className="row-link" onClick={() => nav(`/activities/${a.strava_id}`)}>
                  <td>{shortDate(a.start_date)}</td>
                  <td style={{ textAlign: "left" }}>{sport(a.sport_type)}</td>
                  <td style={{ textAlign: "left" }}>
                    {a.name}{a.imported && <span className="chip" style={{ marginLeft: 6 }}>import</span>}
                  </td>
                  <td>{num(a.distance_km, 2)} km</td>
                  <td>{a.duration_str}</td>
                  <td>{a.avg_pace_str}</td>
                  <td>{num(a.avg_hr)}</td>
                  <td>{num(a.total_elevation_m)} m</td>
                </tr>
              ))}
            </tbody>
          </table>
          {data!.count === 0 && <p className="muted" style={{ textAlign: "center" }}>Sin actividades en el rango.</p>}
        </Card>
      )}
    </div>
  );
}
