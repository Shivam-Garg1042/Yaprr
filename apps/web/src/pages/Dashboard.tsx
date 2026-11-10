import { Link } from "react-router-dom";
import { api } from "../api";
import CallsTable from "../components/CallsTable";
import Filters, { useFilters } from "../components/Filters";
import { CompareTable, KpiRow, OutcomeBars } from "../components/StatsPanel";
import { Header, useLoad } from "../components/ui";

export default function Dashboard() {
  const [f, setF] = useFilters();
  const key = JSON.stringify(f);
  const ov = useLoad(() => api.overview(f), [key]);
  const calls = useLoad(() => api.calls(f, 8), [key]);
  const agents = useLoad(() => api.agents(), []);
  const names = Object.fromEntries((agents.data ?? []).map((a) => [a.id, a.name]));
  return (
    <>
      <Header eyebrow="Overview" title="How your agents are doing"
        sub="Every number comes from real call records: latency per stage, cost per minute, outcomes.">
        <Link className="btn pri" to="/agents/new">+ New agent</Link>
      </Header>
      <Filters value={f} onChange={setF} />
      {ov.error && <div className="banner bad">Can't reach the API: {ov.error}</div>}
      <KpiRow t={ov.data?.totals} />
      {!f.agent_id && (
        <div className="card">
          <div className="card-h"><h3>Agents compared</h3><span className="sub">best value per column in green</span></div>
          <CompareTable first="Agent" rows={(ov.data?.by_agent ?? []).map((r) => ({
            ...r, key: r.agent_id ?? "none",
            title: r.agent_id ? <Link to={`/agents/${r.agent_id}`}>{r.name}</Link> : r.name,
          }))} />
        </div>
      )}
      <section className="grid g-2">
        <div className="card">
          <div className="card-h"><h3>Recent calls</h3><Link className="btn sm ghost" to={`/calls?${new URLSearchParams(window.location.search)}`}>All {calls.data?.total ?? ""} calls</Link></div>
          <CallsTable rows={calls.data?.items ?? []} agentNames={names} />
        </div>
        <div className="card">
          <div className="card-h"><h3>Outcomes</h3></div>
          <OutcomeBars outcomes={ov.data?.totals.outcomes} />
        </div>
      </section>
    </>
  );
}
