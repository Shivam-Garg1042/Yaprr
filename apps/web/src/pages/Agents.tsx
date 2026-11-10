import { Link } from "react-router-dom";
import { api, fmtInr, fmtMs, label } from "../api";
import { Header, Status, useLoad } from "../components/ui";

export default function Agents() {
  const { data, error } = useLoad(() => api.agents());
  return (
    <>
      <Header eyebrow="Build" title="Agents" sub="An agent = a script + voice + LLM + tools + the questions asked after every call.">
        <Link className="btn pri" to="/agents/new">+ New agent</Link>
      </Header>
      {error && <div className="banner bad">{error}</div>}
      <section className="grid g-cards">
        {(data ?? []).map((a) => (
          <Link key={a.id} to={`/agents/${a.id}`} className="card" style={{ textDecoration: "none", display: "flex", flexDirection: "column", gap: 12 }}>
            <div className="row">
              <span className={`av ${a.config.use_case}`}>{a.config.persona_name[0] ?? "?"}</span>
              <div className="grow"><h3>{a.name}</h3><div className="sub">{label(a.config.use_case)} · {a.config.language}</div></div>
              <Status value={a.status} />
            </div>
            <div className="row">
              <span className="chip blue">{a.config.llm.provider}:{a.config.llm.model.split("/").pop()}</span>
              <span className="chip">v{a.published_version ?? "–"}</span>
              <span className="chip">{a.config.tools.length} tools</span>
            </div>
            <div className="stats3">
              <div><b>{a.stats.calls}</b><small>calls</small></div>
              <div><b>{fmtMs(a.stats.response_p50_ms)}</b><small>response p50</small></div>
              <div><b>{fmtInr(a.stats.cost_inr_per_min_p50)}</b><small>per min</small></div>
            </div>
          </Link>
        ))}
        <Link to="/agents/new" className="card new-card" style={{ textDecoration: "none" }}>
          <div><div style={{ font: "800 40px/1 var(--display)" }}>+</div>New agent<br /><span className="sub">Start from a blank script</span></div>
        </Link>
      </section>
    </>
  );
}
