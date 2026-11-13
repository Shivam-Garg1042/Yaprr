import { useEffect, useState } from "react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { auth } from "./api";
import { ToastProvider } from "./components/ui";
import AgentEditor from "./pages/AgentEditor";
import Agents from "./pages/Agents";
import CallDetail from "./pages/CallDetail";
import Calls from "./pages/Calls";
import Dashboard from "./pages/Dashboard";

const NAV: [string, [string, string][]][] = [
  ["Overview", [["/", "Dashboard"]]],
  ["Build", [["/agents", "Agents"]]],
  ["Analyze", [["/calls", "Calls"]]],
];

function Login() {
  const [token, setToken] = useState("");
  return (
    <div style={{ minHeight: "100vh", display: "grid", placeItems: "center", padding: 16 }}>
      <form className="card" style={{ width: "min(380px, 100%)", display: "grid", gap: 12 }}
        onSubmit={(e) => { e.preventDefault(); auth.set(token.trim()); window.location.reload(); }}>
        <h2>yaprr</h2>
        <p className="sub" style={{ margin: 0 }}>Enter the access token for this deployment.</p>
        <div className="field"><label htmlFor="tok">Access token</label>
          <input id="tok" type="password" autoComplete="current-password" value={token} onChange={(e) => setToken(e.target.value)} /></div>
        <button className="btn pri" disabled={!token.trim()}>Sign in</button>
      </form>
    </div>
  );
}

export default function App() {
  const [locked, setLocked] = useState(false);
  useEffect(() => {
    const onUnauthorized = () => { auth.clear(); setLocked(true); };
    window.addEventListener("yaprr:unauthorized", onUnauthorized);
    return () => window.removeEventListener("yaprr:unauthorized", onUnauthorized);
  }, []);
  if (locked) return <Login />;
  return (
    <ToastProvider>
      <div className="app">
        <aside className="side" aria-label="Main navigation">
          <NavLink to="/" className="brand">
            <span className="logo" aria-hidden="true">
              <svg width="20" height="20" viewBox="0 0 20 20">
                {[[2, 7, 6], [6.4, 3, 14], [10.8, 5, 10], [15.2, 8, 4]].map(([x, y, h]) => (
                  <rect key={x} x={x} y={y} width="2.6" height={h} rx="1.3" fill="#1A1430" />
                ))}
              </svg>
            </span>
            <span><b>yaprr</b><small>voice agents, measured</small></span>
          </NavLink>
          <nav>
            {NAV.map(([group, items]) => (
              <div className="navgroup" key={group}>
                <span>{group}</span>
                {items.map(([to, label]) => (
                  <NavLink key={to} to={to} end={to === "/"}>{label}</NavLink>
                ))}
              </div>
            ))}
          </nav>
          <div className="foot">
            v0.3 {auth.get() && <button className="btn sm ghost" style={{ marginLeft: 6 }} onClick={() => { auth.clear(); window.location.reload(); }}>Sign out</button>}
          </div>
        </aside>
        <main className="main">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/agents" element={<Agents />} />
            <Route path="/agents/new" element={<AgentEditor />} />
            <Route path="/agents/:id" element={<AgentEditor />} />
            <Route path="/calls" element={<Calls />} />
            <Route path="/calls/:id" element={<CallDetail />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
      </div>
    </ToastProvider>
  );
}
