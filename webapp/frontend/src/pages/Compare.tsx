import { useEffect, useState } from "react";
import { useActivities, useCompare } from "../api/hooks";
import { Card, Empty, ErrorState, Loading, Metric } from "../components/ui";
import { CompareChart } from "../components/charts";
import { dur, num, pace, shortDate, sport } from "../lib/format";

export default function Compare() {
  const acts = useActivities(365);
  const [a, setA] = useState<number | undefined>();
  const [b, setB] = useState<number | undefined>();
  const options = acts.data?.activities ?? [];

  // Sensible defaults: two most recent activities.
  useEffect(() => {
    if (options.length >= 2 && a === undefined && b === undefined) {
      setA(options[0].strava_id);
      setB(options[1].strava_id);
    }
  }, [options.length]);

  const cmp = useCompare(a, b);

  return (
    <div>
      <h1 className="page-title">Comparar sesiones</h1>

      <div className="grid cols-2" style={{ marginBottom: 16 }}>
        <Card title="Sesión A"><Selector value={a} onChange={setA} options={options} accent="var(--accent)" /></Card>
        <Card title="Sesión B"><Selector value={b} onChange={setB} options={options} accent="var(--blue)" /></Card>
      </div>

      {a !== undefined && a === b && <Card><Empty label="Elige dos sesiones distintas." /></Card>}
      {cmp.isLoading && <Loading label="Comparando sesiones…" />}
      {cmp.error && <ErrorState error={cmp.error} />}

      {cmp.data && (
        <>
          <div className="grid cols-4" style={{ marginBottom: 16 }}>
            <DeltaCard label="Δ Distancia" value={cmp.data.deltas.distance_km} unit="km" digits={2} />
            <DeltaCard label="Δ Tiempo" value={cmp.data.deltas.moving_time_s ? cmp.data.deltas.moving_time_s / 60 : null} unit="min" digits={1} />
            <DeltaCard label="Δ Ritmo" value={cmp.data.deltas.pace_delta_sec_km} unit="s/km" digits={0} invert />
            <DeltaCard label="Δ FC media" value={cmp.data.deltas.avg_hr} unit="bpm" digits={1} invert />
          </div>

          <div className="grid cols-2" style={{ marginBottom: 16 }}>
            <SummaryCard title="Sesión A" s={cmp.data.a.summary} color="var(--accent)" />
            <SummaryCard title="Sesión B" s={cmp.data.b.summary} color="var(--blue)" />
          </div>

          <Card title="Ritmo por km (A vs B)" style={{ marginBottom: 16 }}>
            <CompareChart a={cmp.data.a.splits} b={cmp.data.b.splits} metric="pace" />
          </Card>
          <Card title="FC por km (A vs B)" style={{ marginBottom: 16 }}>
            <CompareChart a={cmp.data.a.splits} b={cmp.data.b.splits} metric="hr" />
          </Card>

          <Card title="Parciales lado a lado">
            <SideBySideSplits a={cmp.data.a.splits} b={cmp.data.b.splits} />
          </Card>
        </>
      )}
    </div>
  );
}

function Selector({ value, onChange, options, accent }:
  { value?: number; onChange: (v: number) => void; options: any[]; accent: string }) {
  return (
    <select value={value ?? ""} onChange={(e) => onChange(Number(e.target.value))}
      style={{ width: "100%", padding: "8px 10px", background: "var(--bg-elev)", color: "var(--text)",
               border: `1px solid ${accent}55`, borderRadius: 8, fontSize: 14 }}>
      <option value="" disabled>Elige una sesión…</option>
      {options.map((o) => (
        <option key={o.strava_id} value={o.strava_id}>
          {shortDate(o.start_date)} · {sport(o.sport_type)} · {num(o.distance_km, 2)} km · {o.avg_pace_str}/km
        </option>
      ))}
    </select>
  );
}

function DeltaCard({ label, value, unit, digits, invert }:
  { label: string; value: number | null; unit: string; digits: number; invert?: boolean }) {
  // invert=true means "lower is better" (pace, HR): negative delta => green.
  let color = "var(--muted)";
  if (value != null && Math.abs(value) > (unit === "s/km" ? 1 : 0.05)) {
    const better = invert ? value < 0 : value > 0;
    color = better ? "var(--green)" : "var(--red)";
  }
  const sign = value != null && value > 0 ? "+" : "";
  return (
    <Card>
      <Metric label={label} color={color}
        value={value == null ? "–" : `${sign}${num(value, digits)}`} sub={unit + " (A − B)"} />
    </Card>
  );
}

function SummaryCard({ title, s, color }: { title: string; s: any; color: string }) {
  return (
    <Card title={title}>
      <div style={{ fontWeight: 800, fontSize: 16, marginBottom: 4, color }}>{s.name}</div>
      <div className="muted" style={{ fontSize: 13, marginBottom: 10 }}>{shortDate(s.start_date)} · {sport(s.sport_type)}</div>
      <div style={{ display: "flex", gap: 18, flexWrap: "wrap" }}>
        <Metric label="Dist" value={`${num(s.distance_km, 2)}`} sub="km" />
        <Metric label="Tiempo" value={dur(s.moving_time_s)} />
        <Metric label="Ritmo" value={s.avg_pace} sub="min/km" />
        <Metric label="FC" value={num(s.avg_hr)} sub={`máx ${num(s.max_hr)}`} />
      </div>
    </Card>
  );
}

function SideBySideSplits({ a, b }: { a: any[]; b: any[] }) {
  const n = Math.max(a.length, b.length);
  if (!n) return <Empty label="Sin parciales." />;
  return (
    <table className="data">
      <thead>
        <tr><th>Km</th><th>Ritmo A</th><th>Ritmo B</th><th>Δ s/km</th><th>FC A</th><th>FC B</th><th>Δ FC</th></tr>
      </thead>
      <tbody>
        {Array.from({ length: n }, (_, i) => {
          const ra = a[i], rb = b[i];
          const dp = ra?.pace_min_km != null && rb?.pace_min_km != null
            ? Math.round((ra.pace_min_km - rb.pace_min_km) * 60) : null;
          const dh = ra?.avg_hr != null && rb?.avg_hr != null ? Math.round(ra.avg_hr - rb.avg_hr) : null;
          return (
            <tr key={i}>
              <td style={{ textAlign: "left" }}>{i + 1}</td>
              <td>{ra?.pace ?? "–"}</td>
              <td>{rb?.pace ?? "–"}</td>
              <td style={{ color: dp == null ? undefined : dp < 0 ? "var(--green)" : dp > 0 ? "var(--red)" : undefined }}>
                {dp == null ? "–" : `${dp > 0 ? "+" : ""}${dp}`}
              </td>
              <td>{num(ra?.avg_hr)}</td>
              <td>{num(rb?.avg_hr)}</td>
              <td>{dh == null ? "–" : `${dh > 0 ? "+" : ""}${dh}`}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
