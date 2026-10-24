import { useCallback, useEffect, useState, type FormEvent } from "react";
import { MailPlus, RefreshCw, UserMinus, Users } from "lucide-react";
import { api as request } from "./api";

type Invitation = { id: string; email: string; role: string; status: string; expires_at: string; created_at: string };

export default function WorkspaceInvitations({ workspaceId, role }: { workspaceId: string; role: string }) {
  const [rows, setRows] = useState<Invitation[]>([]);
  const [email, setEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("member");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const base = `/workspaces/${workspaceId}/invitations`;
  const reload = useCallback(async () => {
    if (workspaceId) setRows(await request<Invitation[]>(base));
  }, [base, workspaceId]);

  useEffect(() => { setRows([]); setMessage(""); void reload().catch((error) => setMessage(error.message)); }, [reload]);
  if (!workspaceId || !["owner", "admin"].includes(role)) return null;

  async function invite(event: FormEvent) {
    event.preventDefault(); setBusy(true); setMessage("");
    try {
      await request<Invitation>(base, { method: "POST", body: JSON.stringify({ email, role: inviteRole }) });
      setEmail(""); setMessage(`Invitation sent to ${email}.`); await reload();
    } catch (error) { setMessage(error instanceof Error ? error.message : "Could not send invitation."); }
    finally { setBusy(false); }
  }

  async function revoke(id: string) {
    setBusy(true); setMessage("");
    try { await request(`${base}/${id}`, { method: "DELETE" }); await reload(); setMessage("Invitation revoked."); }
    catch (error) { setMessage(error instanceof Error ? error.message : "Could not revoke invitation."); }
    finally { setBusy(false); }
  }

  return <section className="meeting-card workspace-invitations">
    <div className="meeting-section-title"><div><h2>Workspace invitations</h2><p><Users size={13} /> Invite people to join this workspace</p></div></div>
    <form className="meeting-inline-form" onSubmit={(event) => void invite(event)}>
      <label className="field"><span>Email address</span><input type="email" required maxLength={320} autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="person@example.com" /></label>
      <label className="field"><span>Workspace role</span><select value={inviteRole} onChange={(event) => setInviteRole(event.target.value)}><option value="member">Member</option><option value="event_manager">Event manager</option>{role === "owner" && <option value="admin">Administrator</option>}</select></label>
      <button className="button button-primary" disabled={busy}><MailPlus size={15} /> Send invitation</button>
    </form>
    {message && <p className="meeting-message" role="status">{message}</p>}
    <div className="meeting-record-list">{rows.map((row) => <article className="meeting-record" key={row.id}><div><strong>{row.email}</strong><small>{row.role} · {row.status}{row.status === "pending" ? ` · expires ${new Date(row.expires_at).toLocaleDateString()}` : ` · invited ${new Date(row.created_at).toLocaleDateString()}`}</small></div><div className="record-actions">{row.status === "pending" && <button className="meeting-remove" type="button" disabled={busy} onClick={() => void revoke(row.id)}><UserMinus size={14} /> Revoke</button>}</div></article>)}
      {!rows.length && <p className="meeting-empty">No workspace invitations yet.</p>}</div>
    <button className="meeting-link" type="button" disabled={busy} onClick={() => void reload().catch((error) => setMessage(error.message))}><RefreshCw size={14} /> Refresh invitations</button>
  </section>;
}
