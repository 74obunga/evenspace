import { useEffect, useState } from "react";
import { CheckCircle2, ShieldCheck } from "lucide-react";

const API_BASE = (import.meta.env.VITE_API_BASE_URL || "http://localhost:8000/api/v1").replace(/\/$/, "");

export default function EmailVerification({ token, onDone }: { token: string; onDone: () => void }) {
  const [message, setMessage] = useState("Verifying your email…");
  const [error, setError] = useState(false);

  useEffect(() => {
    let active = true;
    void fetch(`${API_BASE}/auth/email-verification/complete`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token }),
    }).then(async (response) => {
      const data = await response.json().catch(() => null) as { message?: string; detail?: string } | null;
      if (!response.ok) throw new Error(data?.detail ?? `Request failed (${response.status})`);
      if (active) setMessage(data?.message ?? "Email verified. You can now sign in.");
    }).catch((reason: unknown) => {
      if (active) { setError(true); setMessage(reason instanceof Error ? reason.message : "This verification link is invalid or expired."); }
    });
    return () => { active = false; };
  }, [token]);

  return <main className="meeting-shell">
    <header className="meeting-header"><a className="brand" href="/"><span className="brand-mark"><span /></span><span>evenspace</span></a><span className="meeting-tag"><ShieldCheck size={14} /> ACCOUNT SECURITY</span></header>
    <section className="meeting-welcome"><span className="meeting-kicker"><ShieldCheck size={15} /> EMAIL VERIFICATION</span><h1>Confirm your <em>email.</em></h1><p>Verification links are single-use and expire after 24 hours.</p></section>
    <section className="meeting-card auth-card" role={error ? "alert" : "status"}>
      <div className="meeting-join-confirmation"><CheckCircle2 size={22} /><div><strong>{message}</strong>{!error && <span>You may now sign in to your workspace.</span>}</div></div>
      <button className="button button-primary full-width" type="button" onClick={onDone}>Continue to sign in</button>
    </section>
    <footer className="footer"><span>EVENSPACE</span><span>Verified workspace accounts</span></footer>
  </main>;
}
