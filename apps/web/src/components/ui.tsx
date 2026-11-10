import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

export function Header({ eyebrow, title, sub, children }: { eyebrow: string; title: string; sub?: string; children?: ReactNode }) {
  return (
    <header className="top">
      <div>
        <div className="eyebrow">{eyebrow}</div>
        <h1>{title}</h1>
        {sub && <p>{sub}</p>}
      </div>
      <div className="row">{children}</div>
    </header>
  );
}

export function Kpi({ label, value, sub, hero }: { label: string; value: ReactNode; sub?: ReactNode; hero?: boolean }) {
  return (
    <div className={`card kpi ${hero ? "hero" : ""}`}>
      <span className="lab">{label}</span>
      <span className="val">{value}</span>
      {sub && <span className="sub">{sub}</span>}
    </div>
  );
}

const OUTCOME_TONE: Record<string, string> = {
  promise_to_pay: "good", already_paid: "good", interested: "good", visit_booked: "good",
  callback_requested: "blue", undecided: "", no_conversation: "", refused: "bad", not_interested: "bad",
  dispute: "warn", escalated: "warn", wrong_number: "",
};
export function Outcome({ value }: { value: string | null | undefined }) {
  if (!value) return <span className="chip">pending</span>;
  return <span className={`chip ${OUTCOME_TONE[value] ?? ""}`}>{value.replace(/_/g, " ")}</span>;
}

export function Status({ value }: { value: string }) {
  const tone = value === "live" ? "good" : value === "paused" ? "warn" : value === "archived" ? "bad" : "";
  return <span className={`chip ${tone}`}>{value}</span>;
}

export function Switch({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <label className="sw">
      <input type="checkbox" checked={checked} aria-label={label} onChange={(e) => onChange(e.target.checked)} />
      <span />
    </label>
  );
}

const ToastCtx = createContext<(msg: string) => void>(() => {});
export const useToast = () => useContext(ToastCtx);
export function ToastProvider({ children }: { children: ReactNode }) {
  const [msg, setMsg] = useState<string | null>(null);
  const show = useCallback((m: string) => setMsg(m), []);
  useEffect(() => {
    if (!msg) return;
    const t = setTimeout(() => setMsg(null), 2400);
    return () => clearTimeout(t);
  }, [msg]);
  return (
    <ToastCtx.Provider value={show}>
      {children}
      {msg && <div className="toast" role="status">{msg}</div>}
    </ToastCtx.Provider>
  );
}

export function useLoad<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let alive = true;
    setError(null);
    fn().then((d) => alive && setData(d)).catch((e) => alive && setError(String(e.message ?? e)));
    return () => { alive = false };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  return { data, error, reload: () => setTick((t) => t + 1), setData };
}
