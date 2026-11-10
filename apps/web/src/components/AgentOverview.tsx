import { api, type Agent } from "../api";
import CallsTable from "./CallsTable";
import Filters, { useFilters } from "./Filters";
import { CompareTable, KpiRow, OutcomeBars } from "./StatsPanel";
import { useLoad } from "./ui";

/** Per-agent dashboard: same filters and numbers as the global one, scoped to this agent,
 *  plus a version-by-version comparison (did v3's shorter prompt actually help?). */
export default function AgentOverview({ agent }: { agent: Agent }) {
  const [f, setF] = useFilters({ agent_id: agent.id });
  const key = JSON.stringify(f);
  const ov = useLoad(() => api.overview(f), [key]);
  const calls = useLoad(() => api.calls(f, 10), [key]);
  const versions = Array.from({ length: agent.published_version ?? 0 }, (_, i) => i + 1).reverse();
  return (
    <div className="grid">
      <Filters value={f} onChange={setF} hideAgent versions={versions} />
      <KpiRow t={ov.data?.totals} />
      <div className="card">
        <div className="card-h"><h3>Versions compared</h3><span className="sub">same filters; best value per column in green</span></div>
        <CompareTable first="Version" rows={(ov.data?.by_version ?? []).map((r) => ({
          ...r, key: String(r.version), title: r.version ? `v${r.version}` : "draft",
        }))} />
      </div>
      <section className="grid g-2">
        <div className="card">
          <div className="card-h"><h3>Calls</h3><span className="sub">{calls.data?.total ?? 0} total</span></div>
          <CallsTable rows={calls.data?.items ?? []} />
        </div>
        <div className="card"><div className="card-h"><h3>Outcomes</h3></div><OutcomeBars outcomes={ov.data?.totals.outcomes} /></div>
      </section>
    </div>
  );
}
