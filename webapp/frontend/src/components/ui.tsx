import type { ReactNode } from "react";

export function Card({ title, children, style }: { title?: string; children: ReactNode; style?: React.CSSProperties }) {
  return (
    <div className="card" style={style}>
      {title && <h3>{title}</h3>}
      {children}
    </div>
  );
}

export function Metric({ label, value, sub, color }: { label: string; value: ReactNode; sub?: ReactNode; color?: string }) {
  return (
    <div className="metric">
      <span className="label">{label}</span>
      <span className="value tnum" style={color ? { color } : undefined}>{value}</span>
      {sub && <span className="sub">{sub}</span>}
    </div>
  );
}

export function Loading({ label }: { label?: string }) {
  return (
    <div className="center" style={{ padding: 40, flexDirection: "column", gap: 12 }}>
      <div className="spinner" />
      {label && <span className="muted">{label}</span>}
    </div>
  );
}

export function ErrorState({ error }: { error: unknown }) {
  const msg = error instanceof Error ? error.message : String(error);
  return <div className="error-box">⚠ {msg}</div>;
}

export function Badge({ label, color }: { label: string; color: string }) {
  return (
    <span className="badge" style={{ background: `${color}22`, color, border: `1px solid ${color}55` }}>
      {label}
    </span>
  );
}

export function Empty({ label }: { label: string }) {
  return <div className="muted" style={{ padding: 20, textAlign: "center" }}>{label}</div>;
}
