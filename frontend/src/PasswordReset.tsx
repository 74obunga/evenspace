import { useState, type FormEvent } from "react";
import { CheckCircle2, KeyRound, ShieldCheck } from "lucide-react";
import { API_BASE } from "./apiBase";

export default function PasswordReset({ token, onDone }: { token: string; onDone: () => void }) {
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [message, setMessage] = useState("");
  const [complete, setComplete] = useState(false);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (password !== confirmation) { setMessage("The passwords do not match."); return; }
    setBusy(true); setMessage("");
    try {
      const response = await fetch(`${API_BASE}/auth/password-reset/complete`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, password }),
      });
      const data = await response.json().catch(() => null) as { message?: string; detail?: string } | null;
      if (!response.ok) throw new Error(data?.detail ?? `Request failed (${response.status})`);
      setComplete(true); setMessage(data?.message ?? "Password updated.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not update the password.");
    } finally { setBusy(false); }
  }

  return <main className="meeting-shell">
    <header className="meeting-header"><a className="brand" href="/"><span className="brand-mark"><span /></span><span>evenspace</span></a><span className="meeting-tag"><ShieldCheck size={14} /> ACCOUNT SECURITY</span></header>
    <section className="meeting-welcome"><span className="meeting-kicker"><KeyRound size={15} /> PASSWORD RESET</span><h1>Secure your <em>account.</em></h1><p>Choose a new password with at least 12 characters.</p></section>
    <form className="meeting-card auth-card" onSubmit={(event) => void submit(event)}>
      <h2>{complete ? "Password updated" : "Choose a new password"}</h2>
      {complete ? <div className="meeting-join-confirmation" role="status"><CheckCircle2 size={22} /><div><strong>{message}</strong><span>You can now sign in with your new password.</span></div></div> : <>
        <label className="field"><span>New password</span><input required type="password" minLength={12} maxLength={72} autoComplete="new-password" value={password} onChange={(event) => setPassword(event.target.value)} /></label>
        <label className="field"><span>Confirm new password</span><input required type="password" minLength={12} maxLength={72} autoComplete="new-password" value={confirmation} onChange={(event) => setConfirmation(event.target.value)} /></label>
        {message && <p className="meeting-message" role="alert">{message}</p>}
        <button className="button button-primary full-width" disabled={busy}>{busy ? "Updating password…" : "Update password"}</button>
      </>}
      {complete && <button className="button button-primary full-width" type="button" onClick={onDone}>Continue to sign in</button>}
    </form>
    <footer className="footer"><span>EVENSPACE</span><span>One-time secure reset link</span></footer>
  </main>;
}
