import { Fragment } from "react";
import { Link, useParams } from "react-router-dom";
import { api, fmtDur, fmtInr, fmtMs, label } from "../api";
import { Header, Outcome, useLoad } from "../components/ui";

const STAGES: [string, string][] = [
  ["response", "Response (what the caller waits)"], ["end_of_utterance", "End of utterance"],
  ["transcription", "Transcription"], ["llm_ttft", "LLM first token"], ["tts_ttfb", "TTS first audio"],
];

export default function CallDetail() {
  const { id = "" } = useParams();
  const { data: c, error } = useLoad(() => api.call(id), [id]);
  if (error) return <div className="banner bad">{error}</div>;
  if (!c) return <p className="empty">Loading…</p>;
  const answers = c.dispositions.answers ?? {};
  return (
    <>
      <Header eyebrow={`Call · ${c.room_name}`} title={`${fmtDur(c.duration_s)} · ${label(c.ended_by)}`}
        sub={`${new Date(c.started_at).toLocaleString()} · agent v${c.agent_version ?? "draft"}`}>
        <Outcome value={c.outcome} />
        {c.agent_id && <Link className="btn ghost" to={`/agents/${c.agent_id}`}>Open agent</Link>}
      </Header>
      <section className="grid g-2">
        <div className="card">
          <div className="card-h"><h3>Transcript</h3><span className="sub">dashed = agent was interrupted</span></div>
          <div className="msgs" style={{ maxHeight: "none" }}>
            {c.transcript.map((t, i) => (
              <div key={i} className={`msg ${t.role} ${t.interrupted ? "int" : ""}`}>
                <span className="spk">{t.role}</span>{t.text}
              </div>
            ))}
            {c.tool_calls.map((t, i) => <div key={`t${i}`} className="chip pink mono">{t.at}s · {t.name}({t.arguments})</div>)}
          </div>
        </div>
        <div className="grid" style={{ alignContent: "start" }}>
          <div className="card">
            <h3 style={{ marginBottom: 10 }}>Latency</h3>
            <div className="tbl-wrap"><table>
              <thead><tr><th>Stage</th><th>p50</th><th>p95</th><th>n</th></tr></thead>
              <tbody>{STAGES.map(([k, l]) => {
                const s = c.metrics.latency?.[k];
                return <tr key={k}><td>{l}</td><td className="mono">{fmtMs(s?.p50_ms)}</td><td className="mono">{fmtMs(s?.p95_ms)}</td><td className="mono">{s?.n ?? 0}</td></tr>;
              })}</tbody>
            </table></div>
          </div>
          <div className="card">
            <h3 style={{ marginBottom: 10 }}>Cost</h3>
            <dl className="kv">
              <dt>Total</dt><dd>{fmtInr(c.cost_inr)}</dd>
              <dt>Per minute</dt><dd>{fmtInr(c.cost_inr_per_min)}</dd>
              <dt>LLM failovers</dt><dd>{c.llm_failovers ?? 0}</dd>
              {Object.entries(c.metrics.cost?.usd ?? {}).map(([k, v]) => <Fragment key={k}><dt>{k} (USD)</dt><dd className="mono">${v}</dd></Fragment>)}
            </dl>
          </div>
          <div className="card">
            <h3 style={{ marginBottom: 10 }}>Dispositions</h3>
            {c.dispositions.error && <div className="banner bad">{c.dispositions.error}</div>}
            <dl className="kv">{Object.entries(answers).map(([k, v]) => <Fragment key={k}><dt>{label(k)}</dt><dd>{String(v ?? "—")}</dd></Fragment>)}</dl>
          </div>
          <div className="card">
            <h3 style={{ marginBottom: 10 }}>Pipeline</h3>
            <dl className="kv">{["agent_name", "llm", "llm_fallbacks", "stt", "tts"].map((k) =>
              <Fragment key={k}><dt>{label(k)}</dt><dd className="mono">{Array.isArray(c.pipeline[k]) ? (c.pipeline[k] as string[]).join(" → ") : String(c.pipeline[k] ?? "—")}</dd></Fragment>)}</dl>
          </div>
        </div>
      </section>
    </>
  );
}
