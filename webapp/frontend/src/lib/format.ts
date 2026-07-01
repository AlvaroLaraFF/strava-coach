// Formatting + Spanish label maps (backend returns neutral tokens; UI localizes).

export function pace(minPerKm?: number | null): string {
  if (!minPerKm || minPerKm <= 0) return "–";
  const m = Math.floor(minPerKm);
  const s = Math.round((minPerKm - m) * 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function dur(seconds?: number | null): string {
  if (!seconds) return "–";
  const s = Math.floor(seconds);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`
           : `${m}:${String(sec).padStart(2, "0")}`;
}

export function num(v?: number | null, digits = 0): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  return v.toFixed(digits);
}

const MONTHS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
export function shortDate(iso?: string | null): string {
  if (!iso) return "–";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso.slice(0, 10);
  return `${d.getDate()} ${MONTHS[d.getMonth()]}`;
}
export function weekday(iso: string): string {
  const d = new Date(iso + (iso.length <= 10 ? "T00:00:00Z" : ""));
  return ["dom", "lun", "mar", "mié", "jue", "vie", "sáb"][d.getUTCDay()];
}

export const VERDICT: Record<string, { label: string; color: string }> = {
  detraining: { label: "Muy fresco (posible desentrenamiento)", color: "var(--teal)" },
  fresh: { label: "Fresco", color: "var(--teal)" },
  optimal: { label: "Óptimo", color: "var(--green)" },
  fatigued: { label: "Fatigado", color: "var(--amber)" },
  high_risk: { label: "Muy fatigado — riesgo alto", color: "var(--red)" },
  unknown: { label: "Sin datos", color: "var(--muted)" },
};

export const STATE: Record<string, { label: string; color: string }> = {
  matched: { label: "Completada", color: "var(--green)" },
  unplanned: { label: "Extra (sin plan)", color: "var(--blue)" },
  rest: { label: "Descanso", color: "var(--muted)" },
  planned: { label: "Planificada", color: "var(--amber)" },
  missed: { label: "No realizada", color: "var(--red)" },
  empty: { label: "", color: "transparent" },
};

export const SPORT_LABEL: Record<string, string> = {
  Run: "Carrera", Ride: "Ciclismo", Swim: "Natación", Rest: "Descanso",
  Walk: "Marcha", Hike: "Senderismo", WeightTraining: "Fuerza",
};
export function sport(s?: string): string {
  return (s && SPORT_LABEL[s]) || s || "–";
}

export const SESSION_TYPE_LABEL: Record<string, string> = {
  easy: "Suave", tempo: "Tempo", interval: "Series", long: "Tirada larga",
  fartlek: "Fartlek", recovery: "Recuperación", race: "Carrera",
  strength: "Fuerza", rest: "Descanso",
};
export function sessionType(s?: string): string {
  return (s && SESSION_TYPE_LABEL[s]) || s || "–";
}
