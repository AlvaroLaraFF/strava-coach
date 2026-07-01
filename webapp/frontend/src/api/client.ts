// Thin fetch wrapper: every backend response is {success, data|error}.
// We unwrap it here so callers deal only with `data` (or a thrown Error).

export async function api<T = unknown>(path: string): Promise<T> {
  const res = await fetch(`/api${path}`, { headers: { Accept: "application/json" } });
  let body: any = null;
  try {
    body = await res.json();
  } catch {
    throw new Error(`Respuesta no válida del servidor (${res.status})`);
  }
  if (!body?.success) {
    throw new Error(body?.error || `Error ${res.status}`);
  }
  return body.data as T;
}

export function qs(params: Record<string, string | number | undefined | null>): string {
  const parts = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== null && v !== "")
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`);
  return parts.length ? `?${parts.join("&")}` : "";
}
