import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, label, type Agent, type AgentConfig, type LLMSpec, type Provider, type Question } from "../api";
import AgentOverview from "../components/AgentOverview";
import TalkToAgent from "../components/TalkToAgent";
import { Header, Status, Switch, useLoad, useToast } from "../components/ui";

const BLANK: AgentConfig = {
  use_case: "collections", language: "Hinglish", persona_name: "Neha",
  opening_line: "नमस्ते, मैं {persona_name} बात कर रही हूँ। क्या मेरी बात {customer_name} जी से हो रही है?",
  prompt: "## Role\nYou are {persona_name}, calling {customer_name} about ...\n\n## Flow (one step per turn)\n1. ...\n\n## Objections\n- ...",
  variables: ["persona_name", "customer_name"], tools: ["hangup"],
  voice: { provider: "cartesia", voice_id: "f786b574-daa5-4673-aa0c-cbe3e8534c02", language: "hi", speed: 1.1 },
  llm: { provider: "groq", model: "qwen/qwen3.8-27b", temperature: 0.4, reasoning_effort: "none",
    fallbacks: [{ provider: "openai", model: "gpt-4.1-mini", reasoning_effort: "" }, { provider: "google", model: "gemini-3.5-flash", reasoning_effort: "" }] },
  stt: { provider: "deepgram", model: "nova-3", language: "hi" },
  turn: { endpoint_min_delay: null, endpoint_max_delay: null, interrupt_min_duration: null, interrupt_min_words: null, preemptive_generation: null },
  safety: { max_call_seconds: 360, user_away_timeout: 12, max_inactivity_prompts: 2 },
  dispositions: [
    { id: "call_outcome", type: "enum", question: "Final outcome of the call?", choices: ["promise_to_pay", "callback_requested", "refused", "undecided"] },
    { id: "summary", type: "text", question: "2-3 sentence summary.", choices: [] },
  ],
};

const LLM_PRESETS: Record<string, { model: string; reasoning_effort: string }[]> = {
  groq: [{ model: "qwen/qwen3.8-27b", reasoning_effort: "none" }, { model: "openai/gpt-oss-20b", reasoning_effort: "low" }],
  google: [{ model: "gemini-3.5-flash-lite", reasoning_effort: "" }, { model: "gemini-3.5-flash", reasoning_effort: "" }],
  openai: [{ model: "gpt-4.1-mini", reasoning_effort: "" }, { model: "gpt-4.1-nano", reasoning_effort: "" }],
  cerebras: [{ model: "gpt-oss-120b", reasoning_effort: "low" }],
};

const TABS = ["Overview", "Script", "Voice & model", "Tools", "After the call", "Safety", "Talk to agent", "Versions"] as const;
const NEEDS_SAVED: Tab[] = ["Overview", "Talk to agent", "Versions"];
type Tab = (typeof TABS)[number];

export default function AgentEditor() {
  const { id } = useParams();
  const isNew = !id;
  const nav = useNavigate();
  const toast = useToast();
  const [tab, setTab] = useState<Tab>(isNew ? "Script" : "Overview");
  const [name, setName] = useState("New agent");
  const [cfg, setCfg] = useState<AgentConfig>(BLANK);
  const [agent, setAgent] = useState<Agent | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const tools = useLoad(() => api.tools());
  const versions = useLoad(() => (id ? api.versions(id) : Promise.resolve([])), [id, agent?.published_version]);

  useEffect(() => {
    if (!id) return;
    api.agent(id).then((a) => { setAgent(a); setName(a.name); setCfg(a.config); setDirty(false); }).catch((e) => setError(e.message));
  }, [id]);

  const set = <K extends keyof AgentConfig>(k: K, v: AgentConfig[K]) => { setCfg({ ...cfg, [k]: v }); setDirty(true); };
  const detected = Array.from(new Set(Array.from((cfg.prompt + " " + cfg.opening_line).matchAll(/\{([a-z_][a-z0-9_]*)\}/g)).map((m) => m[1])));

  async function save(): Promise<Agent | null> {
    setError(null);
    const config = { ...cfg, variables: Array.from(new Set([...cfg.variables.filter((v) => detected.includes(v)), ...detected])) };
    try {
      const a = isNew ? await api.createAgent(name, config) : await api.updateAgent(id!, { name, config });
      setAgent(a); setCfg(a.config); setDirty(false);
      toast("Draft saved");
      if (isNew) nav(`/agents/${a.id}`, { replace: true });
      return a;
    } catch (e) { setError((e as Error).message); return null; }
  }

  async function publish() {
    const a = dirty || isNew ? await save() : agent;
    if (!a) return;
    const note = window.prompt?.("What changed in this version?", "") ?? "";
    try {
      const v = await api.publish(a.id, note);
      setAgent({ ...a, published_version: v.version, status: a.status === "draft" ? "live" : a.status });
      toast(`Published v${v.version}`);
    } catch (e) { setError((e as Error).message); }
  }

  async function duplicate() {
    if (!agent) return;
    try { const d = await api.duplicate(agent.id); toast("Copied as a new draft"); nav(`/agents/${d.id}`); setTab("Script"); }
    catch (e) { setError((e as Error).message); }
  }

  async function setStatus(status: Agent["status"]) {
    if (!agent) return;
    try { setAgent(await api.updateAgent(agent.id, { status })); toast(`Agent ${status}`); } catch (e) { setError((e as Error).message); }
  }

  return (
    <>
      <Header eyebrow={isNew ? "Build · new agent" : `Build · ${agent?.published_version ? `published v${agent.published_version}` : "never published"}`}
        title={name} sub={dirty ? "Unsaved changes" : agent ? `Last saved ${new Date(agent.updated_at).toLocaleString()}` : undefined}>
        {agent && <Status value={agent.status} />}
        {agent && agent.status !== "archived" && agent.published_version && (
          <button className="btn ghost" onClick={() => setStatus(agent.status === "live" ? "paused" : "live")}>
            {agent.status === "live" ? "Pause" : "Go live"}
          </button>
        )}
        {agent && <button className="btn ghost" onClick={duplicate}>Duplicate</button>}
        <button className="btn" onClick={save} disabled={!dirty && !isNew}>Save draft</button>
        <button className="btn pri" onClick={publish}>Publish version</button>
      </Header>
      {error && <div className="banner bad">{error}</div>}

      <section className="card">
        <div className="tabs" role="tablist">
          {TABS.map((t) => (
            <button key={t} role="tab" aria-selected={tab === t} className={`tab ${tab === t ? "on" : ""}`}
              disabled={isNew && NEEDS_SAVED.includes(t)} onClick={() => setTab(t)}>{t}</button>
          ))}
        </div>

        {tab === "Overview" && agent && <AgentOverview agent={agent} />}

        {tab === "Script" && (
          <div className="form">
            <div className="field"><label htmlFor="name">Agent name</label>
              <input id="name" type="text" value={name} onChange={(e) => { setName(e.target.value); setDirty(true); }} /></div>
            <div className="field"><label htmlFor="persona">Persona name</label>
              <input id="persona" type="text" value={cfg.persona_name} onChange={(e) => set("persona_name", e.target.value)} /></div>
            <div className="field"><label htmlFor="usecase">Use case</label>
              <select id="usecase" value={cfg.use_case} onChange={(e) => set("use_case", e.target.value as AgentConfig["use_case"])}>
                {["collections", "sales", "support", "other"].map((u) => <option key={u}>{u}</option>)}</select></div>
            <div className="field"><label htmlFor="lang">Language</label>
              <input id="lang" type="text" value={cfg.language} onChange={(e) => set("language", e.target.value)} /></div>
            <div className="field full"><label htmlFor="open">Opening line</label>
              <textarea id="open" className="short" value={cfg.opening_line} onChange={(e) => set("opening_line", e.target.value)} />
              <span className="hint">Spoken straight to TTS when the call connects (no LLM, ~100 ms). Write numbers as words.</span></div>
            <div className="field full"><label htmlFor="prompt">Script / instructions</label>
              <textarea id="prompt" value={cfg.prompt} onChange={(e) => set("prompt", e.target.value)} />
              <span className="hint">
                Use {"{variables}"} for call-time values. Detected: {detected.length ? detected.map((v) => <span key={v} className="chip mono" style={{ marginRight: 4 }}>{v}</span>) : "none"}.
                {" "}~{Math.round((cfg.prompt.length + cfg.opening_line.length) / 4)} tokens if English. Hindi script costs ~3-4× more; keep instructions in English.
              </span></div>
          </div>
        )}

        {tab === "Voice & model" && (
          <div className="form">
            <div className="field"><label htmlFor="prov">LLM provider</label>
              <select id="prov" value={cfg.llm.provider} onChange={(e) => {
                const provider = e.target.value as AgentConfig["llm"]["provider"];
                set("llm", { ...cfg.llm, provider, ...LLM_PRESETS[provider][0] });
              }}>{Object.keys(LLM_PRESETS).map((p) => <option key={p}>{p}</option>)}</select></div>
            <div className="field"><label htmlFor="model">Model</label>
              <input id="model" type="text" list="models" value={cfg.llm.model} onChange={(e) => set("llm", { ...cfg.llm, model: e.target.value })} />
              <datalist id="models">{LLM_PRESETS[cfg.llm.provider].map((m) => <option key={m.model} value={m.model} />)}</datalist></div>
            <div className="field"><label htmlFor="temp">Temperature</label>
              <input id="temp" type="number" step="0.1" min="0" max="1.5" value={cfg.llm.temperature} onChange={(e) => set("llm", { ...cfg.llm, temperature: Number(e.target.value) })} /></div>
            <div className="field"><label htmlFor="reason">Reasoning effort</label>
              <input id="reason" type="text" value={cfg.llm.reasoning_effort} onChange={(e) => set("llm", { ...cfg.llm, reasoning_effort: e.target.value })} />
              <span className="hint">Voice needs speed: Groq Qwen "none", gpt-oss "low".</span></div>
            <div className="field full"><label>Fallback models (tried in order)</label>
              <Fallbacks value={cfg.llm.fallbacks} onChange={(fb) => set("llm", { ...cfg.llm, fallbacks: fb })} />
              <span className="hint">Used when the primary errors (429/503) or hangs &gt;10 s. Pick other providers: one outage shouldn't take them all. The worker skips any whose API key isn't set.</span></div>
            <div className="field"><label htmlFor="voice">Cartesia voice ID</label>
              <input id="voice" type="text" value={cfg.voice.voice_id} onChange={(e) => set("voice", { ...cfg.voice, voice_id: e.target.value })} /></div>
            <div className="field"><label htmlFor="speed">Speaking speed</label>
              <input id="speed" type="number" step="0.05" min="0.6" max="1.5" value={cfg.voice.speed} onChange={(e) => set("voice", { ...cfg.voice, speed: Number(e.target.value) })} /></div>
            <div className="field"><label htmlFor="stt">Speech-to-text language</label>
              <select id="stt" value={cfg.stt.language} onChange={(e) => set("stt", { ...cfg.stt, language: e.target.value })}>
                <option value="hi">hi (Hindi)</option><option value="multi">multi (auto-detect)</option><option value="en">en</option></select></div>
            <div className="field"><label htmlFor="emin">Reply after silence (s)</label>
              <input id="emin" type="number" step="0.05" placeholder="worker default 0.4" value={cfg.turn.endpoint_min_delay ?? ""}
                onChange={(e) => set("turn", { ...cfg.turn, endpoint_min_delay: e.target.value === "" ? null : Number(e.target.value) })} /></div>
            <div className="field"><label htmlFor="emax">Max wait if unsure (s)</label>
              <input id="emax" type="number" step="0.1" placeholder="worker default 2.0" value={cfg.turn.endpoint_max_delay ?? ""}
                onChange={(e) => set("turn", { ...cfg.turn, endpoint_max_delay: e.target.value === "" ? null : Number(e.target.value) })} /></div>
            <div className="field"><label htmlFor="iw">Words needed to interrupt agent</label>
              <input id="iw" type="number" min="0" max="5" placeholder="worker default 0" value={cfg.turn.interrupt_min_words ?? ""}
                onChange={(e) => set("turn", { ...cfg.turn, interrupt_min_words: e.target.value === "" ? null : Number(e.target.value) })} /></div>
          </div>
        )}

        {tab === "Tools" && (
          <div>
            {Object.entries(tools.data ?? {}).map(([t, desc]) => (
              <div className="toggle-row" key={t}>
                <div className="grow"><b className="mono">{t}()</b><div className="sub">{desc}</div></div>
                <Switch label={t} checked={cfg.tools.includes(t)}
                  onChange={(on) => set("tools", on ? [...cfg.tools, t] : cfg.tools.filter((x) => x !== t))} />
              </div>
            ))}
          </div>
        )}

        {tab === "After the call" && <Dispositions questions={cfg.dispositions} onChange={(q) => set("dispositions", q)} />}

        {tab === "Safety" && (
          <div className="form">
            <div className="field"><label htmlFor="maxs">Max call length (s)</label>
              <input id="maxs" type="number" value={cfg.safety.max_call_seconds} onChange={(e) => set("safety", { ...cfg.safety, max_call_seconds: Number(e.target.value) })} /></div>
            <div className="field"><label htmlFor="away">Silence before "hello?" (s)</label>
              <input id="away" type="number" value={cfg.safety.user_away_timeout} onChange={(e) => set("safety", { ...cfg.safety, user_away_timeout: Number(e.target.value) })} /></div>
            <div className="field"><label htmlFor="nudges">"Hello?" nudges before hang-up</label>
              <input id="nudges" type="number" value={cfg.safety.max_inactivity_prompts} onChange={(e) => set("safety", { ...cfg.safety, max_inactivity_prompts: Number(e.target.value) })} /></div>
            <p className="hint full">These run in code, not in the prompt, so they hold even when the LLM misbehaves.</p>
          </div>
        )}

        {tab === "Talk to agent" && agent && (
          <>
            {dirty && <div className="banner warn" style={{ marginBottom: 12 }}>You have unsaved changes. Save the draft first; test calls load the saved draft or a published version.</div>}
            <TalkToAgent agentId={agent.id} variables={cfg.variables} published={!!agent.published_version} />
          </>
        )}

        {tab === "Versions" && (
          <div className="tbl-wrap"><table>
            <thead><tr><th>Version</th><th>Published</th><th>Note</th><th>Model</th><th>Prompt size</th></tr></thead>
            <tbody>{(versions.data ?? []).map((v) => (
              <tr key={v.version}><td><b>v{v.version}</b>{v.version === agent?.published_version && <span className="chip good" style={{ marginLeft: 6 }}>current</span>}</td>
                <td>{new Date(v.created_at).toLocaleString()}</td><td>{v.note || "—"}</td>
                <td className="mono">{v.config.llm.provider}:{v.config.llm.model}</td><td className="mono">{v.config.prompt.length} chars</td></tr>
            ))}</tbody>
          </table>{(versions.data ?? []).length === 0 && <p className="empty">Not published yet.</p>}</div>
        )}
      </section>
    </>
  );
}

function Dispositions({ questions, onChange }: { questions: Question[]; onChange: (q: Question[]) => void }) {
  const upd = (i: number, q: Partial<Question>) => onChange(questions.map((x, j) => (j === i ? { ...x, ...q } : x)));
  return (
    <div className="grid">
      <p className="sub" style={{ margin: 0 }}>After every call an LLM answers these from the transcript and the tools that actually ran. Off-list answers become “unknown”.</p>
      {questions.map((q, i) => (
        <div className="q" key={i}>
          <div className="field"><label htmlFor={`qid${i}`}>Field id</label>
            <input id={`qid${i}`} type="text" value={q.id} onChange={(e) => upd(i, { id: e.target.value })} /></div>
          <div className="field"><label htmlFor={`qq${i}`}>Question</label>
            <input id={`qq${i}`} type="text" value={q.question} onChange={(e) => upd(i, { question: e.target.value })} /></div>
          <div className="field"><label htmlFor={`qt${i}`}>Type</label>
            <select id={`qt${i}`} value={q.type} onChange={(e) => upd(i, { type: e.target.value as Question["type"] })}>
              <option value="enum">choice</option><option value="bool">yes / no</option><option value="text">text</option></select></div>
          <div style={{ alignSelf: "end" }}><button className="btn sm ghost" onClick={() => onChange(questions.filter((_, j) => j !== i))}>Remove</button></div>
          {q.type === "enum" && (
            <div className="field full"><label htmlFor={`qc${i}`}>Choices (comma separated)</label>
              <input id={`qc${i}`} type="text" value={q.choices.join(", ")}
                onChange={(e) => upd(i, { choices: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })} />
              <span className="hint">{q.choices.map(label).join(" · ")}</span></div>
          )}
        </div>
      ))}
      <div><button className="btn" onClick={() => onChange([...questions, { id: `question_${questions.length + 1}`, type: "text", question: "", choices: [] }])}>+ Add question</button></div>
    </div>
  );
}

function Fallbacks({ value, onChange }: { value: LLMSpec[]; onChange: (v: LLMSpec[]) => void }) {
  const upd = (i: number, p: Partial<LLMSpec>) => onChange(value.map((x, j) => (j === i ? { ...x, ...p } : x)));
  return (
    <div className="grid" style={{ gap: 8 }}>
      {value.map((f, i) => (
        <div className="row" key={i}>
          <span className="chip mono">{i + 1}</span>
          <select aria-label={`Fallback ${i + 1} provider`} style={{ width: "auto" }} value={f.provider}
            onChange={(e) => { const p = e.target.value as Provider; upd(i, { provider: p, ...LLM_PRESETS[p][0] }); }}>
            {Object.keys(LLM_PRESETS).map((p) => <option key={p}>{p}</option>)}
          </select>
          <input aria-label={`Fallback ${i + 1} model`} type="text" list={`fbm${i}`} className="grow" style={{ width: "auto" }} value={f.model}
            onChange={(e) => upd(i, { model: e.target.value })} />
          <datalist id={`fbm${i}`}>{LLM_PRESETS[f.provider].map((m) => <option key={m.model} value={m.model} />)}</datalist>
          <button className="btn sm ghost" onClick={() => onChange(value.filter((_, j) => j !== i))}>Remove</button>
        </div>
      ))}
      {value.length < 3 && <div><button className="btn sm" onClick={() => onChange([...value, { provider: "google", model: "gemini-3.5-flash", reasoning_effort: "" }])}>+ Add fallback</button></div>}
    </div>
  );
}
