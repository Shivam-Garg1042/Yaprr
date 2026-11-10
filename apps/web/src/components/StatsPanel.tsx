import { fmtInr, fmtMs, fmtPct, label, type Stats } from "../api";
import { Kpi } from "./ui";

export function KpiRow({ t }: { t?: Stats }) {
  return (
    <section className="grid g-kpi">
      <Kpi hero label="Calls" value={t?.calls ?? "—"} sub={`${t?.connected ?? 0} connected · ${t?.minutes ?? 0} min`} />
      <Kpi label="Response p50" value={fmtMs(t?.response_p50_ms)} sub={`p95 ${fmtMs(t?.response_p95_ms)}`} />
      <Kpi label="LLM first token p50" value={fmtMs(t?.llm_ttft_p50_ms)} sub={`failover in ${fmtPct(t?.failover_rate)} of calls`} />
      <Kpi label="Cost / min (p50)" value={fmtInr(t?.cost_inr_per_min_p50)} sub={`total ${fmtInr(t?.cost_inr_total)}`} />
      <Kpi label="Interrupted replies" value={fmtPct(t?.interrupt_rate)} sub="lower = agent talks less" />
    </section>
  );
}

export function OutcomeBars({ outcomes }: { outcomes?: Record<string, number> }) {
  const rows = Object.entries(outcomes ?? {});
  const max = Math.max(1, ...rows.map(([, n]) => n));
  if (rows.length === 0) return <p className="empty">No calls yet.</p>;
  return (
    <div className="bars">
      {rows.map(([o, n]) => (
        <div className="bar-row" key={o}>
          <span>{label(o)}</span>
          <div className="bar-track"><div className="bar-fill" style={{ width: `${(n / max) * 100}%` }} /></div>
          <b>{n}</b>
        </div>
      ))}
    </div>
  );
}

type Row = Stats & { key: string; title: React.ReactNode };

/** Side-by-side comparison (agents or versions); the best value per column is highlighted. */
export function CompareTable({ rows, first }: { rows: Row[]; first: string }) {
  if (rows.length === 0) return <p className="empty">Nothing to compare yet.</p>;
  const best = (pick: (r: Row) => number | null) => {
    const vals = rows.map(pick).filter((v): v is number => v != null);
    return vals.length > 1 ? Math.min(...vals) : null;
  };
  const cols: [string, (r: Row) => number | null, (v: number | null) => string][] = [
    ["Response p50", (r) => r.response_p50_ms, fmtMs], ["Response p95", (r) => r.response_p95_ms, fmtMs],
    ["LLM p50", (r) => r.llm_ttft_p50_ms, fmtMs], ["₹/min", (r) => r.cost_inr_per_min_p50, (v) => fmtInr(v)],
    ["Interrupted", (r) => r.interrupt_rate, fmtPct], ["Failover", (r) => r.failover_rate, fmtPct],
  ];
  return (
    <div className="tbl-wrap"><table>
      <thead><tr><th>{first}</th><th>Calls</th>{cols.map(([h]) => <th key={h}>{h}</th>)}<th>Top outcome</th></tr></thead>
      <tbody>{rows.map((r) => (
        <tr key={r.key}>
          <td>{r.title}</td><td className="mono">{r.calls}</td>
          {cols.map(([h, pick, fmt]) => {
            const b = best(pick);
            return <td key={h} className={`mono ${b != null && pick(r) === b ? "best" : ""}`}>{fmt(pick(r))}</td>;
          })}
          <td>{label(Object.keys(r.outcomes)[0] ?? "—")}</td>
        </tr>
      ))}</tbody>
    </table></div>
  );
}
