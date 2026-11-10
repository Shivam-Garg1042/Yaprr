import { useNavigate } from "react-router-dom";
import { fmtInr, fmtMs, fmtPct, type CallSummary } from "../api";
import { Outcome } from "./ui";

export default function CallsTable({ rows, agentNames }: { rows: CallSummary[]; agentNames?: Record<string, string> }) {
  const nav = useNavigate();
  if (rows.length === 0) return <p className="empty">No calls match these filters.</p>;
  return (
    <div className="tbl-wrap">
      <table>
        <thead><tr>
          <th>When</th>{agentNames && <th>Agent</th>}<th>Outcome</th><th>Duration</th><th>Response p50</th>
          <th>LLM p50</th><th>₹/min</th><th>Interrupted</th><th>Failover</th>
        </tr></thead>
        <tbody>
          {rows.map((c) => (
            <tr key={c.id} className="click" tabIndex={0} onClick={() => nav(`/calls/${c.id}`)}
              onKeyDown={(e) => e.key === "Enter" && nav(`/calls/${c.id}`)}>
              <td>{new Date(c.started_at).toLocaleString()}</td>
              {agentNames && <td>{(c.agent_id && agentNames[c.agent_id]) || "—"} <span className="muted mono">v{c.agent_version ?? "–"}</span></td>}
              <td><Outcome value={c.outcome} /></td>
              <td className="mono">{Math.round(c.duration_s)}s</td>
              <td className="mono">{fmtMs(c.response_p50_ms)}</td>
              <td className="mono">{fmtMs(c.llm_ttft_p50_ms)}</td>
              <td className="mono">{fmtInr(c.cost_inr_per_min)}</td>
              <td className="mono">{fmtPct(c.interrupt_rate)}</td>
              <td>{c.llm_failovers ? <span className="chip warn">{c.llm_failovers}×</span> : <span className="muted">—</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
