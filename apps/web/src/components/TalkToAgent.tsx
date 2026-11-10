import {
  LiveKitRoom,
  RoomAudioRenderer,
  useLocalParticipant,
  useTrackTranscription,
  useVoiceAssistant,
} from "@livekit/components-react";
import { Track } from "livekit-client";
import { useMemo, useState } from "react";
import { api } from "../api";

/** Browser test call: the API mints a LiveKit token whose room dispatches our worker
 *  with {agent_id, version, context}; the worker loads that agent from the DB. */
export default function TalkToAgent({ agentId, variables, published }: { agentId: string; variables: string[]; published: boolean }) {
  const [session, setSession] = useState<{ url: string; token: string; room: string; version: number | null } | null>(null);
  const [useDraft, setUseDraft] = useState(!published);
  const [context, setContext] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function start() {
    setBusy(true);
    setError(null);
    try {
      const filled = Object.fromEntries(Object.entries(context).filter(([, v]) => v.trim()));
      const s = await api.testSession(agentId, { use_draft: useDraft, context: filled });
      setSession({ url: s.livekit_url, token: s.token, room: s.room_name, version: s.agent_version });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (session) {
    return (
      <LiveKitRoom serverUrl={session.url} token={session.token} connect audio video={false}
        onDisconnected={() => setSession(null)} onError={(e) => setError(e.message)}>
        <RoomAudioRenderer />
        <LiveCall room={session.room} version={session.version} onEnd={() => setSession(null)} />
      </LiveKitRoom>
    );
  }

  return (
    <div className="grid">
      <p className="sub" style={{ margin: 0 }}>
        Starts a real call in your browser (mic). The worker must be running: <span className="mono">python main.py dev</span>.
        Leave a value empty to use the demo value.
      </p>
      <div className="form">
        {variables.filter((v) => v !== "persona_name").map((v) => (
          <div className="field" key={v}>
            <label htmlFor={`ctx-${v}`}>{v}</label>
            <input id={`ctx-${v}`} type="text" value={context[v] ?? ""} placeholder="demo value"
              onChange={(e) => setContext({ ...context, [v]: e.target.value })} />
          </div>
        ))}
      </div>
      <label className="row" style={{ fontSize: 14 }}>
        <input type="checkbox" checked={useDraft} disabled={!published} onChange={(e) => setUseDraft(e.target.checked)} />
        Test the unsaved-to-version draft {published ? "" : "(no published version yet)"}
      </label>
      {error && <div className="banner bad">{error}</div>}
      <div><button className="btn pri" disabled={busy} onClick={start}>{busy ? "Connecting…" : "Start test call"}</button></div>
    </div>
  );
}

function LiveCall({ room, version, onEnd }: { room: string; version: number | null; onEnd: () => void }) {
  const { state, agentTranscriptions } = useVoiceAssistant();
  const { localParticipant, microphoneTrack } = useLocalParticipant();
  const micRef = useMemo(
    () => (microphoneTrack ? { participant: localParticipant, publication: microphoneTrack, source: Track.Source.Microphone } : undefined),
    [localParticipant, microphoneTrack],
  );
  const { segments: mine } = useTrackTranscription(micRef);
  const lines = [
    ...agentTranscriptions.map((s) => ({ role: "agent", text: s.text, t: s.firstReceivedTime })),
    ...mine.map((s) => ({ role: "customer", text: s.text, t: s.firstReceivedTime })),
  ].sort((a, b) => a.t - b.t);

  const labelFor: Record<string, string> = {
    disconnected: "Waiting for the agent to join…", connecting: "Connecting…", initializing: "Agent joining…",
    listening: "Listening", thinking: "Thinking", speaking: "Speaking",
  };
  return (
    <div className="grid g-2">
      <div className={`stage ${state === "speaking" ? "speaking" : ""}`}>
        <div className="orb" aria-hidden="true" />
        <h2 style={{ fontSize: 22 }}>{labelFor[state] ?? state}</h2>
        <div className="sub mono">{room} · {version ? `v${version}` : "draft"}</div>
        <button className="btn danger" onClick={onEnd}>End call</button>
        <p className="sub" style={{ margin: 0 }}>The call record (latency, cost, outcome) shows up in Calls after you end.</p>
      </div>
      <div className="card">
        <h3 style={{ marginBottom: 10 }}>Live transcript</h3>
        <div className="msgs" aria-live="polite">
          {lines.length === 0 ? <p className="empty">Say hello after the agent greets you.</p> :
            lines.map((l, i) => <div key={i} className={`msg ${l.role}`}><span className="spk">{l.role}</span>{l.text}</div>)}
        </div>
      </div>
    </div>
  );
}
