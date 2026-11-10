// Typed client for the yaprr API (proxied at /api by Vite in dev).

export type QType = "enum" | "bool" | "text";
export type Provider = "google" | "groq" | "openai" | "cerebras";
export interface LLMSpec { provider: Provider; model: string; reasoning_effort: string }
export interface Question { id: string; question: string; type: QType; choices: string[] }
export interface AgentConfig {
  use_case: "collections" | "sales" | "support" | "other";
  language: string;
  persona_name: string;
  opening_line: string;
  prompt: string;
  variables: string[];
  tools: string[];
  voice: { provider: "cartesia"; voice_id: string; language: string; speed: number };
  llm: { provider: Provider; model: string; temperature: number; reasoning_effort: string; fallbacks: LLMSpec[] };
  stt: { provider: "deepgram"; model: string; language: string };
  turn: { endpoint_min_delay: number | null; endpoint_max_delay: number | null; interrupt_min_duration: number | null; interrupt_min_words: number | null; preemptive_generation: boolean | null };
  safety: { max_call_seconds: number; user_away_timeout: number; max_inactivity_prompts: number };
  dispositions: Question[];
}
export interface Stats {
  calls: number; connected: number; minutes: number;
  response_p50_ms: number | null; response_p95_ms: number | null; llm_ttft_p50_ms: number | null;
  cost_inr_total: number; cost_inr_per_min_p50: number | null; interrupt_rate: number | null;
  failover_rate: number | null; outcomes: Record<string, number>;
}
export interface Agent {
  id: string; name: string; status: "draft" | "live" | "paused" | "archived";
  config: AgentConfig; published_version: number | null; created_at: string; updated_at: string; stats: Stats;
}
export interface Version { version: number; note: string; created_at: string; config: AgentConfig }
export interface CallSummary {
  id: string; agent_id: string | null; agent_version: number | null; room_name: string; started_at: string;
  duration_s: number; ended_by: string; outcome: string | null; response_p50_ms: number | null;
  response_p95_ms: number | null; llm_ttft_p50_ms: number | null; cost_inr: number | null;
  cost_inr_per_min: number | null; interrupt_rate: number | null; llm_failovers: number | null;
}
export interface CallPage { items: CallSummary[]; total: number; limit: number; offset: number }
export interface CallFilters { agent_id?: string; version?: number; outcome?: string; ended_by?: string; days?: number }
export interface Turn { role: "agent" | "customer"; text: string; interrupted?: boolean }
export interface CallDetail extends CallSummary {
  context: Record<string, string>; pipeline: Record<string, unknown>;
  metrics: { latency?: Record<string, { p50_ms: number | null; p95_ms: number | null; n: number }>; usage?: Record<string, number>; cost?: { inr_total: number; inr_per_minute: number | null; usd: Record<string, number> } };
  dispositions: { answers?: Record<string, unknown> | null; error?: string; status?: string; model?: string; attempts?: number };
  tool_calls: { name: string; arguments: string; at: number }[];
  transcript: Turn[];
}
export interface Overview {
  totals: Stats;
  daily: (Stats & { day: string })[];
  by_agent: (Stats & { agent_id: string | null; name: string })[];
  by_version: (Stats & { agent_id: string | null; version: number | null })[];
}

const qs = (o: object) => {
  const p = new URLSearchParams();
  Object.entries(o).forEach(([k, v]) => v !== undefined && v !== null && v !== "" && p.set(k, String(v)));
  const s = p.toString();
  return s ? `?${s}` : "";
};

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...init });
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const body = await res.json();
      msg = typeof body.detail === "string" ? body.detail
        : Array.isArray(body.detail) ? body.detail.map((d: { loc?: string[]; msg: string }) => `${(d.loc ?? []).slice(-1)[0] ?? ""}: ${d.msg}`).join("; ")
        : JSON.stringify(body);
    } catch { /* keep statusText */ }
    throw new ApiError(res.status, msg);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

export const api = {
  agents: () => req<Agent[]>("/api/agents"),
  agent: (id: string) => req<Agent>(`/api/agents/${id}`),
  createAgent: (name: string, config: AgentConfig) => req<Agent>("/api/agents", { method: "POST", body: JSON.stringify({ name, config }) }),
  updateAgent: (id: string, body: Partial<{ name: string; status: Agent["status"]; config: AgentConfig }>) =>
    req<Agent>(`/api/agents/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  publish: (id: string, note: string) => req<Version>(`/api/agents/${id}/publish`, { method: "POST", body: JSON.stringify({ note }) }),
  versions: (id: string) => req<Version[]>(`/api/agents/${id}/versions`),
  tools: () => req<Record<string, string>>("/api/tools"),
  testSession: (id: string, body: { use_draft: boolean; context: Record<string, string> }) =>
    req<{ livekit_url: string; token: string; room_name: string; agent_version: number | null }>(`/api/agents/${id}/test-session`, { method: "POST", body: JSON.stringify(body) }),
  calls: (f: CallFilters = {}, limit = 50, offset = 0) => req<CallPage>(`/api/calls${qs({ ...f, limit, offset })}`),
  call: (id: string) => req<CallDetail>(`/api/calls/${id}`),
  overview: (f: CallFilters = {}) => req<Overview>(`/api/stats/overview${qs(f)}`),
  duplicate: (id: string) => req<Agent>(`/api/agents/${id}/duplicate`, { method: "POST" }),
};

export const fmtMs = (v: number | null | undefined) => (v == null ? "—" : v >= 1000 ? `${(v / 1000).toFixed(2)}s` : `${Math.round(v)}ms`);
export const fmtInr = (v: number | null | undefined, digits = 2) => (v == null ? "—" : `₹${v.toFixed(digits)}`);
export const fmtPct = (v: number | null | undefined) => (v == null ? "—" : `${Math.round(v * 100)}%`);
export const fmtDur = (s: number) => `${Math.floor(s / 60)}m ${String(Math.round(s % 60)).padStart(2, "0")}s`;
export const label = (s: string) => s.replace(/_/g, " ");
