import { useEffect, useState, type FormEvent } from "react";
import { CheckCircle2, Mail, Users } from "lucide-react";

const API_BASE = (import.meta.env.VITE_API_BASE_URL || "http://localhost:8000/api/v1").replace(/\/$/, "");
type InvitationInfo = { email: string; role: string; workspace_name: string; expires_at: string };

export default function InvitationAccept({ token, onDone }: { token: string; onDone: () => void }) {
  const [info, setInfo] = useState<InvitationInfo | null>(null);
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState("Checking invitation…");
  const [error, setError] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let active = true;
    void fetch(`${API_BASE}/auth/invitations/info`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token }),
    }).then(async (response) => {
      const data = await response.json().catch(() => null) as InvitationInfo & { detail?: string } | null;
      if (!response.ok) throw new Error(data?.detail ?? `Request failed (${response.status})`);
      if (active && data) { setInfo(data); setMessage(""); }
    }).catch((reason: unknown) => {
      if (active) { setError(true); setMessage(reason instanceof Error ? reason.message : "This invitation link is invalid or expired."); }
    });
    return () => { active = false; };
  }, [token]);

  async function accept(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError(false); setMessage("");
    try {
      const response = await fetch(`${API_BASE}/auth/invitations/accept`, {
        method: "POST", credentials: "include", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, password }),
      });
      const data = await response.json().catch(() => null) as { detail?: string } | null;
      if (!response.ok) throw new Error(data?.detail ?? `Request failed (${response.status})`);
      onDone();
    } catch (reason) {
      setError(true); setMessage(reason instanceof Error ? reason.message : "Could not accept invitation.");
    } finally { setBusy(false); }
  }

  return <main className="meeting-shell">
    <header className="meeting-header"><a className="brand" href="/"><span className="brand-mark"><span /></span><span>evenspace</span></a><span className="meeting-tag"><Users size={14} /> WORKSPACE INVITATION</span></header>
    <section className="meeting-welcome"><span className="meeting-kicker"><Mail size={15} /> JOIN A WORKSPACE</span><h1>You're <em>invited.</em></h1><p>Accept the invitation to access your organization's EvenSpace workspace.</p></section>
    <form className="meeting-card auth-card" onSubmit={(event) => void accept(event)}>
      {info ? <><div className="meeting-join-confirmation"><CheckCircle2 size={22} /><div><strong>{info.workspace_name}</strong><span>{info.email} · {info.role} access</span></div></div>
        <label className="field"><span>{info.email} account password, or create a password</span><input type="password" required minLength={12} maxLength={72} autoComplete="new-password" value={password} onChange={(event) => setPassword(event.target.value)} /><small className="field-help">Use your existing EvenSpace password if you already have an account with this email. The link expires {new Date(info.expires_at).toLocaleString()}.</small></label>
        {message && <p className="meeting-message" role={error ? "alert" : "status"}>{message}</p>}
        <button className="button button-primary full-width" disabled={busy}>{busy ? "Joining…" : "Accept invitation"}</button>
      </> : <p className="meeting-message" role={error ? "alert" : "status"}>{message}</p>}
    </form>
    <footer className="footer"><span>EVENSPACE</span><span>Workspace access</span></footer>
  </main>;
}
