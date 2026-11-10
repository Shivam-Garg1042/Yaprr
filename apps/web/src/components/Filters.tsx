import { useSearchParams } from "react-router-dom";
import { api, label, type CallFilters } from "../api";
import { useLoad } from "./ui";

const OUTCOMES = ["promise_to_pay", "already_paid", "callback_requested", "refused", "dispute", "escalated",
  "undecided", "interested", "visit_booked", "not_interested", "no_conversation", "pending"];

/** Filters live in the URL (?agent_id=…&days=7), so a filtered dashboard is a shareable link. */
export function useFilters(fixed: CallFilters = {}): [CallFilters, (f: CallFilters) => void] {
  const [sp, setSp] = useSearchParams();
  const f: CallFilters = {
    agent_id: fixed.agent_id ?? (sp.get("agent_id") || undefined),
    version: sp.get("version") ? Number(sp.get("version")) : undefined,
    outcome: sp.get("outcome") || undefined,
    days: sp.get("days") ? Number(sp.get("days")) : 14,
  };
  const set = (next: CallFilters) => {
    const p = new URLSearchParams(sp);
    (["agent_id", "version", "outcome", "days"] as const).forEach((k) => {
      const v = next[k];
      if (v === undefined || v === "" || (k === "agent_id" && fixed.agent_id)) p.delete(k);
      else p.set(k, String(v));
    });
    p.delete("page");
    setSp(p, { replace: true });
  };
  return [f, set];
}

export default function Filters({ value, onChange, hideAgent, versions }:
  { value: CallFilters; onChange: (f: CallFilters) => void; hideAgent?: boolean; versions?: number[] }) {
  const agents = useLoad(() => api.agents(), []);
  return (
    <div className="filters" role="group" aria-label="Filters">
      {!hideAgent && (
        <select aria-label="Agent" value={value.agent_id ?? ""} onChange={(e) => onChange({ ...value, agent_id: e.target.value || undefined, version: undefined })}>
          <option value="">All agents</option>
          {(agents.data ?? []).map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
        </select>
      )}
      {versions && versions.length > 0 && (
        <select aria-label="Version" value={value.version ?? ""} onChange={(e) => onChange({ ...value, version: e.target.value ? Number(e.target.value) : undefined })}>
          <option value="">All versions</option>
          {versions.map((v) => <option key={v} value={v}>v{v}</option>)}
        </select>
      )}
      <select aria-label="Outcome" value={value.outcome ?? ""} onChange={(e) => onChange({ ...value, outcome: e.target.value || undefined })}>
        <option value="">All outcomes</option>
        {OUTCOMES.map((o) => <option key={o} value={o}>{label(o)}</option>)}
      </select>
      <div className="seg" role="radiogroup" aria-label="Time range">
        {[1, 7, 14, 30, 90].map((d) => (
          <button key={d} role="radio" aria-checked={value.days === d} className={value.days === d ? "on" : ""}
            onClick={() => onChange({ ...value, days: d })}>{d === 1 ? "24h" : `${d}d`}</button>
        ))}
      </div>
    </div>
  );
}
