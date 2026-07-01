import { useMemo, useState } from "react";
import {
  Area, Bar, CartesianGrid, ComposedChart, Legend, Line, LineChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import type { Evolution, PmcPoint, Streams } from "../api/types";
import { pace as fmtPace, shortDate } from "../lib/format";
import { Empty } from "./ui";

const C = {
  accent: "#fc5200", teal: "#2dd4bf", blue: "#60a5fa", amber: "#fbbf24",
  red: "#f87171", green: "#4ade80", purple: "#a78bfa", muted: "#8b93a1", grid: "#262b36",
};
const AXIS = { stroke: C.muted, fontSize: 11, tickLine: false };
const tt = { contentStyle: { background: "#171a21", border: "1px solid #262b36", borderRadius: 8, fontSize: 12 }, labelStyle: { color: C.muted } };

function sparseTicks(xs: string[], n = 6): string[] {
  if (xs.length <= n) return xs;
  const step = Math.ceil(xs.length / n);
  return xs.filter((_, i) => i % step === 0);
}

export function PmcChart({ data }: { data: PmcPoint[] }) {
  if (!data.length) return <Empty label="Sin datos de carga todavía." />;
  const ticks = sparseTicks(data.map((d) => d.day));
  return (
    <ResponsiveContainer width="100%" height={280}>
      <ComposedChart data={data} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
        <CartesianGrid stroke={C.grid} vertical={false} />
        <XAxis dataKey="day" ticks={ticks} tickFormatter={shortDate} {...AXIS} />
        <YAxis {...AXIS} />
        <Tooltip {...tt} labelFormatter={shortDate} />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        <Bar dataKey="load" name="Carga" fill={C.grid} />
        <Line dataKey="ctl" name="Fitness (CTL)" stroke={C.teal} dot={false} strokeWidth={2} />
        <Line dataKey="atl" name="Fatiga (ATL)" stroke={C.amber} dot={false} strokeWidth={2} />
        <Line dataKey="tsb" name="Forma (TSB)" stroke={C.accent} dot={false} strokeWidth={2} />
      </ComposedChart>
    </ResponsiveContainer>
  );
}

export function VdotThresholdChart({ history }: { history: Evolution["snapshot_history"] }) {
  const data = history.filter((h) => h.vdot || h.threshold_pace_min_km)
    .map((h) => ({ day: (h.captured_at || "").slice(0, 10), vdot: h.vdot, tpace: h.threshold_pace_min_km }));
  if (!data.length) return <Empty label="Sin histórico de VDOT / umbral." />;
  return (
    <ResponsiveContainer width="100%" height={240}>
      <ComposedChart data={data} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
        <CartesianGrid stroke={C.grid} vertical={false} />
        <XAxis dataKey="day" ticks={sparseTicks(data.map((d) => d.day))} tickFormatter={shortDate} {...AXIS} />
        <YAxis yAxisId="l" {...AXIS} />
        <YAxis yAxisId="r" orientation="right" reversed tickFormatter={(v) => fmtPace(v)} {...AXIS} />
        <Tooltip {...tt} labelFormatter={shortDate}
          formatter={(v: any, n: any) => (n === "Ritmo umbral" ? [`${fmtPace(v)}/km`, n] : [v, n])} />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        <Line yAxisId="l" dataKey="vdot" name="VDOT" stroke={C.purple} strokeWidth={2} connectNulls dot={{ r: 2 }} />
        <Line yAxisId="r" dataKey="tpace" name="Ritmo umbral" stroke={C.accent} strokeWidth={2} connectNulls dot={{ r: 2 }} />
      </ComposedChart>
    </ResponsiveContainer>
  );
}

export function HrTrendChart({ history }: { history: Evolution["snapshot_history"] }) {
  const data = history.filter((h) => h.hr_max_bpm || h.hr_rest_bpm || h.lthr_bpm)
    .map((h) => ({ day: (h.captured_at || "").slice(0, 10), hrmax: h.hr_max_bpm, lthr: h.lthr_bpm, hrrest: h.hr_rest_bpm }));
  if (!data.length) return <Empty label="Sin histórico de FC." />;
  return (
    <ResponsiveContainer width="100%" height={240}>
      <LineChart data={data} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
        <CartesianGrid stroke={C.grid} vertical={false} />
        <XAxis dataKey="day" ticks={sparseTicks(data.map((d) => d.day))} tickFormatter={shortDate} {...AXIS} />
        <YAxis domain={["dataMin - 5", "dataMax + 5"]} {...AXIS} />
        <Tooltip {...tt} labelFormatter={shortDate} />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        <Line dataKey="hrmax" name="FC máx" stroke={C.red} strokeWidth={2} connectNulls dot={false} />
        <Line dataKey="lthr" name="LTHR" stroke={C.amber} strokeWidth={2} connectNulls dot={false} />
        <Line dataKey="hrrest" name="FC reposo" stroke={C.teal} strokeWidth={2} connectNulls dot={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}

export function PrProgressionChart({ progression }: { progression: Evolution["pr_progression"] }) {
  const efforts = Object.keys(progression);
  const [sel, setSel] = useState(efforts.includes("5K") ? "5K" : efforts[0]);
  if (!efforts.length) return <Empty label="Sin registros para progresión." />;
  const data = (progression[sel] || []).map((p) => ({
    date: p.date, best: +(p.running_best_s / 60).toFixed(2), time_str: p.time_str, is_pr: p.is_pr,
  }));
  return (
    <div>
      <div className="seg" style={{ marginBottom: 10, flexWrap: "wrap" }}>
        {efforts.map((e) => (
          <button key={e} className={e === sel ? "active" : ""} onClick={() => setSel(e)}>{e}</button>
        ))}
      </div>
      <ResponsiveContainer width="100%" height={220}>
        <LineChart data={data} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
          <CartesianGrid stroke={C.grid} vertical={false} />
          <XAxis dataKey="date" ticks={sparseTicks(data.map((d) => d.date))} tickFormatter={shortDate} {...AXIS} />
          <YAxis reversed tickFormatter={(v) => `${Math.floor(v)}:${String(Math.round((v % 1) * 60)).padStart(2, "0")}`} {...AXIS} />
          <Tooltip {...tt} labelFormatter={shortDate}
            formatter={(_: any, __: any, p: any) => [p.payload.time_str, "Mejor marca"]} />
          <Line dataKey="best" name="Mejor acumulada" stroke={C.accent} strokeWidth={2}
            dot={(props: any) => {
              const isPr = data[props.index]?.is_pr;
              return <circle key={props.index} cx={props.cx} cy={props.cy} r={isPr ? 4 : 2}
                fill={isPr ? C.green : C.accent} stroke="none" />;
            }} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export function CompareChart({ a, b, metric }: { a: any[]; b: any[]; metric: "pace" | "hr" }) {
  const key = metric === "pace" ? "pace_min_km" : "avg_hr";
  const maxKm = Math.max(a.length, b.length);
  const data = Array.from({ length: maxKm }, (_, i) => ({
    km: i + 1,
    A: a[i]?.[key] ?? null,
    B: b[i]?.[key] ?? null,
  }));
  if (!data.length) return <Empty label="Sin parciales para comparar." />;
  const isPace = metric === "pace";
  return (
    <ResponsiveContainer width="100%" height={240}>
      <LineChart data={data} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
        <CartesianGrid stroke={C.grid} vertical={false} />
        <XAxis dataKey="km" tickFormatter={(v) => `${v}k`} {...AXIS} />
        <YAxis reversed={isPace} tickFormatter={(v) => (isPace ? fmtPace(v) : v)}
          domain={isPace ? ["dataMin - 0.3", "dataMax + 0.3"] : ["dataMin - 5", "dataMax + 5"]} {...AXIS} />
        <Tooltip {...tt} labelFormatter={(v) => `km ${v}`}
          formatter={(val: any, n: any) => [isPace ? `${fmtPace(val)}/km` : `${val} bpm`, n]} />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        <Line dataKey="A" name="Sesión A" stroke={C.accent} strokeWidth={2} dot={false} connectNulls isAnimationActive={false} />
        <Line dataKey="B" name="Sesión B" stroke={C.blue} strokeWidth={2} dot={false} connectNulls isAnimationActive={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}

export function StreamChart({ streams }: { streams: Streams }) {
  const data = useMemo(() => {
    const dist = (streams.distance?.data as number[]) || [];
    const hr = (streams.heartrate?.data as (number | null)[]) || [];
    const vel = (streams.velocity_smooth?.data as (number | null)[]) || [];
    const alt = (streams.altitude?.data as (number | null)[]) || [];
    const n = dist.length;
    if (!n) return [];
    return Array.from({ length: n }, (_, i) => {
      const v = vel[i];
      // Convert speed→pace; drop stopped/near-zero (would explode the axis).
      let pace: number | null = v && v > 0.6 ? (1000 / v) / 60 : null;
      if (pace != null && pace > 13) pace = null; // walking/stops, not running pace
      return {
        km: +(dist[i] / 1000).toFixed(2),
        hr: hr[i] ?? null,
        pace: pace != null ? +pace.toFixed(3) : null,
        alt: alt[i] ?? null,
      };
    });
  }, [streams]);
  if (!data.length) return <Empty label="Sin series por segundo para esta actividad." />;

  const hasHr = data.some((d) => d.hr != null);
  const hasAlt = data.some((d) => d.alt != null);
  const hrs = data.map((d) => d.hr).filter((x): x is number => x != null);
  const paces = data.map((d) => d.pace).filter((x): x is number => x != null);
  const hrDom: [number, number] = hrs.length ? [Math.min(...hrs) - 8, Math.max(...hrs) + 8] : [0, 200];
  const paceDom: [number, number] = paces.length
    ? [Math.floor(Math.min(...paces) * 10) / 10, Math.ceil(Math.max(...paces) * 10) / 10] : [4, 9];
  const tickEvery = Math.max(1, Math.ceil(data.length / 6));

  return (
    <ResponsiveContainer width="100%" height={260}>
      <ComposedChart data={data} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
        <CartesianGrid stroke={C.grid} vertical={false} />
        <XAxis dataKey="km" interval={tickEvery} tickFormatter={(v) => `${Math.round(v)}k`} {...AXIS} />
        {hasAlt && <YAxis yAxisId="alt" hide domain={["dataMin - 20", "dataMax + 40"]} />}
        <YAxis yAxisId="pace" orientation="right" reversed domain={paceDom}
          tickFormatter={(v) => fmtPace(v)} {...AXIS} />
        {hasHr && <YAxis yAxisId="hr" domain={hrDom} {...AXIS} />}
        <Tooltip {...tt} labelFormatter={(v) => `${v} km`}
          formatter={(val: any, name: any) => (name === "Ritmo" ? [`${fmtPace(val)}/km`, name] : [val, name])} />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        {hasAlt && <Area yAxisId="alt" dataKey="alt" name="Altitud" stroke="none" fill={C.grid} fillOpacity={0.7} isAnimationActive={false} />}
        {hasHr && <Line yAxisId="hr" dataKey="hr" name="FC" stroke={C.red} dot={false} strokeWidth={1.6} connectNulls isAnimationActive={false} />}
        <Line yAxisId="pace" dataKey="pace" name="Ritmo" stroke={C.accent} dot={false} strokeWidth={1.6} connectNulls isAnimationActive={false} />
      </ComposedChart>
    </ResponsiveContainer>
  );
}
