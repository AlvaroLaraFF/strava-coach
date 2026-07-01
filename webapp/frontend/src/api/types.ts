// Loose types mirroring the backend payloads (webapp/backend/service.py).

export interface Snapshot {
  ctl?: number | null;
  atl?: number | null;
  tsb?: number | null;
  vdot?: number | null;
  threshold_pace_min_km?: number | null;
  hr_max_bpm?: number | null;
  hr_rest_bpm?: number | null;
  lthr_bpm?: number | null;
  ftp_w?: number | null;
  weight_kg?: number | null;
  acwr?: number | null;
  captured_at?: string;
  [k: string]: unknown;
}

export interface ActivityBrief {
  strava_id: number;
  name: string;
  sport_type: string;
  start_date: string;
  distance_km: number | null;
  moving_time_s: number | null;
  duration_str: string | null;
  avg_pace_min_km: number | null;
  avg_pace_str: string;
  avg_hr: number | null;
  max_hr: number | null;
  total_elevation_m: number | null;
  imported: boolean;
  has_streams?: boolean;
}

export interface PlannedBlock {
  block_type: string;
  repeat_count: number;
  duration_min?: number | null;
  distance_km?: number | null;
  hr_min_bpm?: number | null;
  hr_max_bpm?: number | null;
  pace_fast_min_km?: number | null;
  pace_slow_min_km?: number | null;
  execution_notes?: string | null;
}

export interface PlannedSession {
  id: number;
  plan_date: string;
  sport_type: string;
  session_type: string;
  phase?: string | null;
  duration_min?: number | null;
  distance_km?: number | null;
  hr_min_bpm?: number | null;
  hr_max_bpm?: number | null;
  pace_fast_min_km?: number | null;
  pace_slow_min_km?: number | null;
  description?: string | null;
  status: string;
  blocks?: PlannedBlock[];
}

export type DayState = "matched" | "unplanned" | "rest" | "planned" | "missed" | "empty";

export interface CalendarDay {
  date: string;
  iso_week: string;
  planned: PlannedSession[];
  executed: ActivityBrief[];
  state: DayState;
}

export interface Dashboard {
  snapshot: Snapshot;
  tsb_verdict: string;
  next_session: PlannedSession | null;
  recent: ActivityBrief[];
}

export interface Stream {
  data: (number | null | [number, number] | boolean)[];
  series_type: string;
  original_size: number;
  resolution: string;
}
export type Streams = Record<string, Stream>;

export interface PmcPoint { day: string; load: number; ctl: number; atl: number; tsb: number; }

export interface Evolution {
  snapshot_history: Snapshot[];
  pmc: PmcPoint[];
  pmc_params: Record<string, number>;
  pr_progression: Record<string, PrPoint[]>;
}
export interface PrPoint {
  date: string; distance_m: number; time_s: number; time_str: string;
  pace_str: string; running_best_s: number; is_pr: boolean;
}

export interface Pr {
  effort_name: string; distance_m: number; time_s: number; time_str: string;
  pace_min_km: number | null; pace_str: string; date: string;
  age_days: number | null; stale: boolean;
}
export interface Prs {
  prs: Pr[];
  predictions: Record<string, { time_s: number; time_str: string }>;
  stale_count: number;
}

// session-analysis is rendered loosely (its shape is rich and optional).
export type SessionAnalysis = Record<string, any>;
