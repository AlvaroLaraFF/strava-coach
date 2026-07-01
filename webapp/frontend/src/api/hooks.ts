import { useQuery } from "@tanstack/react-query";
import { api, qs } from "./client";
import type {
  ActivityBrief, CalendarDay, Dashboard, Evolution, PlannedSession,
  Prs, SessionAnalysis, Snapshot, Streams,
} from "./types";

export function useDashboard() {
  return useQuery({ queryKey: ["dashboard"], queryFn: () => api<Dashboard>("/dashboard") });
}

export function useActivities(days = 120, sport?: string) {
  return useQuery({
    queryKey: ["activities", days, sport],
    queryFn: () => api<{ activities: ActivityBrief[]; count: number }>(
      `/activities${qs({ days, sport, limit: 300 })}`),
  });
}

export function useActivity(id: number) {
  return useQuery({
    queryKey: ["activity", id],
    queryFn: () => api<{ summary: ActivityBrief & Record<string, any>; laps: any[] }>(
      `/activities/${id}`),
  });
}

export function useStreams(id: number, enabled = true) {
  return useQuery({
    queryKey: ["streams", id],
    queryFn: () => api<Streams>(`/activities/${id}/streams${qs({ downsample: 1500 })}`),
    enabled,
  });
}

export function useSessionAnalysis(params: { date?: string; stravaId?: number }) {
  const { date, stravaId } = params;
  return useQuery({
    queryKey: ["session-analysis", date, stravaId],
    queryFn: () => api<SessionAnalysis>(
      `/session-analysis${qs({ date, strava_id: stravaId })}`),
    enabled: !!(date || stravaId !== undefined),
    retry: false,
  });
}

export function useCompare(a?: number, b?: number) {
  return useQuery({
    queryKey: ["compare", a, b],
    queryFn: () => api<{
      a: { summary: any; splits: any[] };
      b: { summary: any; splits: any[] };
      deltas: Record<string, number | null>;
    }>(`/compare${qs({ a, b })}`),
    enabled: a !== undefined && b !== undefined && a !== b,
    retry: false,
  });
}

export function useCalendar(start: string, end: string) {
  return useQuery({
    queryKey: ["calendar", start, end],
    queryFn: () => api<{ start: string; end: string; days: CalendarDay[] }>(
      `/calendar${qs({ start, end })}`),
  });
}

export function useEvolution(days = 365) {
  return useQuery({
    queryKey: ["evolution", days],
    queryFn: () => api<Evolution>(`/evolution${qs({ days })}`),
  });
}

export function usePrs() {
  return useQuery({ queryKey: ["prs"], queryFn: () => api<Prs>("/prs") });
}

export function useHrZones() {
  return useQuery({ queryKey: ["hr-zones"], queryFn: () => api<any>("/hr-zones") });
}

export function useProfile() {
  return useQuery({
    queryKey: ["profile"],
    queryFn: () => api<{ profile: any; snapshot: Snapshot; athlete_id: number }>("/profile"),
  });
}
