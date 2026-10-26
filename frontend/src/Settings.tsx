import { useEffect, useState } from "react";
import { KeyRound, RefreshCw, ShieldCheck, UserRound, Users } from "lucide-react";
import { api } from "./api";
import WorkspaceInvitations from "./WorkspaceInvitations";
import NotificationTemplates from "./NotificationTemplates";

type Workspace = { id: string; name: string; role: string };

export default function Settings() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [workspaceId, setWorkspaceId] = useState("");
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(true);
  const workspace = workspaces.find((item) => item.id === workspaceId);

  useEffect(() => {
    let active = true;
    void Promise.all([api<Workspace[]>("/workspaces"), api<{ email: string }>("/auth/me")])
      .then(([rows, user]) => { if (active) { setWorkspaces(rows); setWorkspaceId(rows[0]?.id ?? ""); setEmail(user.email); } })
      .catch((error: unknown) => { if (active) setMessage(error instanceof Error ? error.message : "Could not load account settings."); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  async function sendPasswordReset() {
    setMessage("");
    try {
      const response = await api<{ message: string }>("/auth/password-reset/request", { method: "POST", body: JSON.stringify({ email }) });
      setMessage(response.message);
    } catch (error) { setMessage(error instanceof Error ? error.message : "Could not request a password reset."); }
  }

  return <main className="meeting-shell settings-shell">
    <section className="meeting-welcome"><span className="meeting-kicker"><ShieldCheck size={15} /> ACCOUNT & WORKSPACE</span><h1>Settings</h1><p>Manage your account security, workspace access, and email notifications.</p></section>
    {message && <div className="notice notice-info" role="status">{message}</div>}
    {loading ? <section className="meeting-card"><p className="meeting-message">Loading your settings…</p></section> : <>
      <section className="meeting-card settings-account" id="account-security">
        <div className="meeting-section-title"><div><h2><UserRound size={17} /> Personal account</h2><p>Signed-in account and security recovery</p></div></div>
        <label className="field"><span>Email address</span><input readOnly value={email} /></label>
        <div className="settings-security-action"><span><KeyRound size={16} /> Password & security <small>Request a secure password reset link by email.</small></span>
          <button className="button button-secondary" type="button" onClick={() => void sendPasswordReset()}>Send reset link</button>
        </div>
      </section>
      <section className="meeting-card" id="workspace-settings">
        <div className="meeting-section-title"><div><h2><Users size={17} /> Workspace access</h2><p>Choose a workspace to manage membership and invitations.</p></div>
          <button className="button button-secondary" type="button" onClick={() => { setLoading(true); void api<Workspace[]>("/workspaces").then(setWorkspaces).catch((error) => setMessage(error.message)).finally(() => setLoading(false)); }}><RefreshCw size={14} /> Refresh</button>
        </div>
        <label className="field"><span>Workspace</span><select value={workspaceId} onChange={(event) => setWorkspaceId(event.target.value)}>{workspaces.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.role.replaceAll("_", " ")}</option>)}</select></label>
        {workspace ? <WorkspaceInvitations workspaceId={workspace.id} role={workspace.role} /> : <p className="meeting-empty">No workspace is available for this account.</p>}
      </section>
      {workspace && <section className="meeting-card" id="notification-settings">
        <div className="meeting-section-title"><div><h2>Email templates</h2><p>Workspace notification templates and delivery content.</p></div></div>
        <NotificationTemplates workspaceId={workspace.id} canManage={["owner", "admin"].includes(workspace.role)} />
      </section>}
    </>}
  </main>;
}
