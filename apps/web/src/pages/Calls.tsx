import { useState } from "react";
import { api } from "../api";
import CallsTable from "../components/CallsTable";
import Filters, { useFilters } from "../components/Filters";
import { Header, useLoad } from "../components/ui";

const PAGE = 25;

export default function Calls() {
  const [f, setF] = useFilters();
  const [offset, setOffset] = useState(0);
  const key = JSON.stringify(f);
  const { data, error } = useLoad(() => api.calls(f, PAGE, offset), [key, offset]);
  const agents = useLoad(() => api.agents(), []);
  const names = Object.fromEntries((agents.data ?? []).map((a) => [a.id, a.name]));
  const total = data?.total ?? 0;
  return (
    <>
      <Header eyebrow="Analyze" title="Calls" sub="Every call with its latency, cost and extracted outcome. Click one for the transcript." />
      <Filters value={f} onChange={(n) => { setOffset(0); setF(n); }} />
      {error && <div className="banner bad">{error}</div>}
      <section className="card">
        <CallsTable rows={data?.items ?? []} agentNames={names} />
        {total > PAGE && (
          <div className="pager">
            <span className="muted">{offset + 1}–{Math.min(offset + PAGE, total)} of {total}</span>
            <button className="btn sm ghost" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>Previous</button>
            <button className="btn sm ghost" disabled={offset + PAGE >= total} onClick={() => setOffset(offset + PAGE)}>Next</button>
          </div>
        )}
      </section>
    </>
  );
}
