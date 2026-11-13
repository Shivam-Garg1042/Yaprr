import { LiveKitRoom, RoomAudioRenderer } from "@livekit/components-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api, isViewer, type SessionOut } from "../api";
import { LiveCall } from "../components/TalkToAgent";
import { Header, useLoad } from "../components/ui";

/** Public "try it": talk to the demo collections agent. No login; the API enforces
 *  a short call, a few calls per visitor per day, and a daily minutes budget. */
export default function Try() {
  const { data: demo, error: loadError, reload } = useLoad(() => api.demo(), []);
  const [session, setSession] = useState<SessionOut | null>(null);
  const [ended, setEnded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function start() {
    setBusy(true);
    setError(null);
    try {
      setSession(await api.demoSession());
      setEnded(false);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const end = () => { setSession(null); setEnded(true); reload(); };

  if (loadError) return <div className="banner bad">{loadError}</div>;
  if (!demo) return <p className="empty">Loading…</p>;
  if (!demo.enabled || !demo.agent || !demo.limits) {
    return <><Header eyebrow="Try it" title="The live demo is off right now" /><p className="sub">Check back later.</p></>;
  }
  const { agent, limits } = demo;
  const minutes = Math.round(limits.max_call_seconds / 60);

  if (session) {
    return (
      <>
        <Header eyebrow="Live demo" title={`On a call with ${agent.persona}`} />
        <LiveKitRoom serverUrl={session.livekit_url} token={session.token} connect audio video={false}
          onDisconnected={end} onError={(e) => setError(e.message)}>
          <RoomAudioRenderer />
          <LiveCall room={session.room_name} version={session.agent_version} onEnd={end}
            limitSeconds={limits.max_call_seconds} note={`Demo calls end automatically after ${minutes} min.`} />
        </LiveKitRoom>
      </>
    );
  }

  return (
    <>
      <Header eyebrow="Try it live" title={`Talk to ${agent.persona}, an EMI reminder agent`}
        sub="A real voice call in your browser, on the same pipeline the dashboard measures: speech-to-text, LLM, text-to-speech, under ~1.5 s per reply." />
      <section className="grid g-2">
        <div className="card grid">
          <h3>Your role</h3>
          <p style={{ margin: 0 }}>
            You're <b>Ramesh</b>. Your EV battery loan EMI of <b>₹4,200</b> is due today and you haven't paid.
            {" "}{agent.persona} speaks Hindi/Hinglish. Reply in Hindi, Hinglish or English.
          </p>
          <ul className="sub" style={{ margin: 0, paddingLeft: 18 }}>
            <li>Promise a date: "kal kar dunga"</li>
            <li>Push back: "paise nahi hain abhi"</li>
            <li>Interrupt her mid-sentence and see if she stops</li>
            <li>Ask for a payment link</li>
          </ul>
          <p className="sub" style={{ margin: 0 }}>Fictional company (Voltly) and fictional loan. Uses your microphone.</p>
          <p className="sub" style={{ margin: 0 }}><b>Your call's transcript is public</b> on the Calls page, so don't share real personal details.</p>
        </div>
        <div className="card grid" style={{ alignContent: "start" }}>
          <h3>Limits</h3>
          <dl className="kv">
            <dt>Call length</dt><dd>{minutes} min max</dd>
            <dt>Your calls left today</dt><dd>{limits.calls_left} of {limits.calls_per_day}</dd>
            <dt>Demo minutes left today</dt><dd>{limits.minutes_left_today}</dd>
          </dl>
          <p className="sub" style={{ margin: 0 }}>Every call costs real money (~₹3/min for STT + LLM + TTS), so the demo is capped.</p>
          {error && <div className="banner bad">{error}</div>}
          {ended && (
            <div className="banner good">
              Call ended. {demo.public_read
                ? <>Its transcript, latency, cost and outcome appear in <Link to="/calls">Calls</Link> in a few seconds.</>
                : "Thanks for trying it."}
            </div>
          )}
          <div>
            <button className="btn pri" disabled={busy || limits.calls_left === 0 || limits.minutes_left_today < minutes} onClick={start}>
              {busy ? "Connecting…" : ended ? "Call again" : "Start call"}
            </button>
          </div>
          {isViewer() && demo.public_read && <p className="sub" style={{ margin: 0 }}>Or look around: <Link to="/">dashboard</Link>, <Link to="/agents">agents</Link>, <Link to="/calls">calls</Link> (read-only).</p>}
        </div>
      </section>
    </>
  );
}
