import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import {
  CalendarDays, CheckCircle2, Copy, Download,
  ExternalLink, KeyRound, Plus, RefreshCw, Search, ShieldAlert,
  Smartphone, Ticket, Trash2, Users,
} from "lucide-react";
import { api } from "./api";

type Workspace = { id: string; name: string; role: string };
type TicketType = { id: string; name: string; description: string | null; price: string; capacity: number | null; registration_count: number };
type OrganizerEvent = {
  id: string; workspace_id: string; title: string; description: string | null; category: string;
  status: string; visibility: string; start_at: string; end_at: string; timezone: string;
  capacity: number | null; registration_count: number; ticket_types: TicketType[];
};
type Registration = {
  id: string; full_name: string; email: string; status: string; ticket_type: string;
  ticket_status: string | null; registered_at: string; checked_in_at: string | null;
};
type ScanDeviceItem = {
  id: string; event_id: string; name: string; expires_at: string; revoked_at: string | null;
  created_at: string; is_active: boolean;
};
type OfflineConflict = {
  id: string; scan_event_id: string; ticket_id: string | null; attendee_name: string | null;
  scanned_at: string; reason: string; status: string; resolution_note: string | null;
};

function csvCell(value: string | null | undefined) {
  return `"${(value ?? "").replaceAll('"', '""')}"`;
}

function localInputDate(daysAhead: number, hour: number) {
  const date = new Date(); date.setDate(date.getDate() + daysAhead); date.setHours(hour, 0, 0, 0);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

export default function OrganizerDashboard({
  onMeetings,
  onGate,
  onParticipant,
  onOpenScanner,
}: {
  onMeetings: () => void;
  onGate: () => void;
  onParticipant?: () => void;
  onOpenScanner?: (eventId: string, token: string) => void;
}) {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [workspaceId, setWorkspaceId] = useState("");
  const [events, setEvents] = useState<OrganizerEvent[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [registrations, setRegistrations] = useState<Registration[]>([]);
  const [devices, setDevices] = useState<ScanDeviceItem[]>([]);
  const [conflicts, setConflicts] = useState<OfflineConflict[]>([]);
  const [conflictNotes, setConflictNotes] = useState<Record<string, string>>({});
  const [newDeviceName, setNewDeviceName] = useState("Gate 1");
  const [newDeviceDays, setNewDeviceDays] = useState("14");
  const [generatedToken, setGeneratedToken] = useState<{ name: string; token: string; expires_at: string } | null>(null);
  const [search, setSearch] = useState("");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState("Conference");
  const [visibility, setVisibility] = useState("public");
  const [startsAt, setStartsAt] = useState(() => localInputDate(7, 9));
  const [endsAt, setEndsAt] = useState(() => localInputDate(7, 17));
  const [capacity, setCapacity] = useState("");
  const [ticketName, setTicketName] = useState("General admission");
  const [ticketCapacity, setTicketCapacity] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState(false);
  const workspaceGeneration = useRef(0);
  const activeWorkspaceId = useRef("");

  const workspace = workspaces.find((row) => row.id === workspaceId);
  const canManage = !!workspace && ["owner", "admin", "event_manager"].includes(workspace.role);
  const selected = events.find((row) => row.id === selectedId) ?? null;
  const base = workspaceId ? `/workspaces/${workspaceId}/events` : "";

  const reloadEvents = useCallback(async () => {
    if (!workspaceId) { setEvents([]); return; }
    const generation = workspaceGeneration.current;
    const requestedWorkspaceId = workspaceId;
    const rows = await api<OrganizerEvent[]>(`/workspaces/${requestedWorkspaceId}/events`);
    if (workspaceGeneration.current !== generation || activeWorkspaceId.current !== requestedWorkspaceId) return;
    setEvents(rows);
    setSelectedId((current) => current && rows.some((row) => row.id === current) ? current : rows[0]?.id ?? "");
  }, [workspaceId]);

  const reloadRegistrations = useCallback(async () => {
    if (!workspaceId || !selectedId || !canManage) { setRegistrations([]); return; }
    const generation = workspaceGeneration.current;
    const requestedWorkspaceId = workspaceId;
    const rows = await api<Registration[]>(`${base}/${selectedId}/registrations`);
    if (workspaceGeneration.current === generation && activeWorkspaceId.current === requestedWorkspaceId) setRegistrations(rows);
  }, [workspaceId, selectedId, canManage, base]);

  const reloadDevices = useCallback(async () => {
    if (!workspaceId || !selectedId || !canManage) { setDevices([]); return; }
    const generation = workspaceGeneration.current;
    const requestedWorkspaceId = workspaceId;
    const rows = await api<ScanDeviceItem[]>(`${base}/${selectedId}/scan-devices`);
    if (workspaceGeneration.current === generation && activeWorkspaceId.current === requestedWorkspaceId) setDevices(rows);
  }, [workspaceId, selectedId, canManage, base]);

  const reloadConflicts = useCallback(async () => {
    if (!workspaceId || !selectedId || !canManage) { setConflicts([]); return; }
    const generation = workspaceGeneration.current;
    const requestedWorkspaceId = workspaceId;
    const rows = await api<OfflineConflict[]>(`${base}/${selectedId}/attendance/conflicts`);
    if (workspaceGeneration.current === generation && activeWorkspaceId.current === requestedWorkspaceId) setConflicts(rows);
  }, [workspaceId, selectedId, canManage, base]);

  function changeWorkspace(id: string) {
    workspaceGeneration.current += 1;
    activeWorkspaceId.current = id;
    setWorkspaceId(id); setSelectedId(""); setEvents([]); setRegistrations([]);
    setDevices([]); setConflicts([]); setGeneratedToken(null); setMessage(""); setError(false);
  }

  useEffect(() => { activeWorkspaceId.current = workspaceId; }, [workspaceId]);

  useEffect(() => {
    let active = true;
    void api<Workspace[]>("/workspaces").then((rows) => {
      if (!active) return;
      setWorkspaces(rows);
      setWorkspaceId((current) => current && rows.some((row) => row.id === current) ? current : rows[0]?.id ?? "");
    }).catch((reason: unknown) => { if (active) { setError(true); setMessage(reason instanceof Error ? reason.message : "Could not load your workspaces."); } })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    setRegistrations([]);
    setDevices([]);
    setConflicts([]);
    setGeneratedToken(null);
    void reloadEvents().catch((reason: unknown) => { setError(true); setMessage(reason instanceof Error ? reason.message : "Could not load events."); });
  }, [reloadEvents]);

  useEffect(() => {
    const generation = workspaceGeneration.current;
    const requestedWorkspaceId = workspaceId;
    const reportFailure = (reason: unknown, fallback: string, clear: () => void) => {
      if (workspaceGeneration.current !== generation || activeWorkspaceId.current !== requestedWorkspaceId) return;
      clear(); setError(true); setMessage(reason instanceof Error ? reason.message : fallback);
    };
    void reloadRegistrations().catch((reason: unknown) => reportFailure(reason, "Could not load registrations.", () => setRegistrations([])));
    void reloadDevices().catch((reason: unknown) => reportFailure(reason, "Could not load scanner devices.", () => setDevices([])));
    void reloadConflicts().catch((reason: unknown) => reportFailure(reason, "Could not load sync conflicts.", () => setConflicts([])));
  }, [workspaceId, reloadRegistrations, reloadDevices, reloadConflicts]);

  const visibleRegistrations = useMemo(() => {
    const query = search.trim().toLocaleLowerCase();
    return registrations.filter((row) => !query || `${row.full_name} ${row.email} ${row.ticket_type} ${row.status}`.toLocaleLowerCase().includes(query));
  }, [registrations, search]);

  const checkedInCount = useMemo(() => registrations.filter((row) => row.checked_in_at !== null).length, [registrations]);
  const attendanceRate = registrations.length > 0 ? Math.round((checkedInCount / registrations.length) * 100) : 0;
  const pendingConflictsCount = useMemo(() => conflicts.filter((c) => c.status === "conflict").length, [conflicts]);

  const totals = useMemo(() => ({
    registrations: events.reduce((sum, row) => sum + row.registration_count, 0),
    upcoming: events.filter((row) => row.status === "published" && new Date(row.start_at) >= new Date()).length,
    capacity: events.reduce((sum, row) => sum + (row.capacity ?? 0), 0),
  }), [events]);

  async function runAction(action: () => Promise<unknown>, success: string) {
    setBusy(true); setMessage(""); setError(false);
    try {
      await action();
      await Promise.all([reloadEvents(), reloadRegistrations(), reloadDevices(), reloadConflicts()]);
      setMessage(success);
    }
    catch (reason) { setError(true); setMessage(reason instanceof Error ? reason.message : "The request could not be completed."); }
    finally { setBusy(false); }
  }

  async function createEvent(event: FormEvent) {
    event.preventDefault();
    await runAction(async () => {
      const created = await api<OrganizerEvent>(base, { method: "POST", body: JSON.stringify({
        title, description: description || null, category, visibility,
        start_at: new Date(startsAt).toISOString(), end_at: new Date(endsAt).toISOString(),
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "Africa/Nairobi",
        capacity: capacity ? Number(capacity) : null,
      }) });
      setTitle(""); setDescription(""); setSelectedId(created.id);
    }, "Event created. Add a ticket type, then publish it when registration is ready.");
  }

  async function addTicket(event: FormEvent) {
    event.preventDefault();
    if (!selected) return;
    await runAction(async () => {
      await api<TicketType>(`${base}/${selected.id}/ticket-types`, { method: "POST", body: JSON.stringify({
        name: ticketName, price: 0, capacity: ticketCapacity ? Number(ticketCapacity) : null,
      }) });
      await reloadEvents();
    }, "Free ticket type added.");
  }

  async function cancelSelected() {
    if (!selected || !window.confirm(`Cancel ${selected.title}? This also notifies registered attendees.`)) return;
    const reason = window.prompt("Reason for cancellation");
    if (!reason?.trim()) return;
    await runAction(() => api(`${base}/${selected.id}/cancel`, { method: "POST", body: JSON.stringify({ reason }) }), "Event cancelled.");
  }

  async function createScanDevice(event: FormEvent) {
    event.preventDefault();
    if (!selected) return;
    await runAction(async () => {
      const result = await api<{ id: string; event_id: string; name: string; token: string; expires_at: string }>(
        `${base}/${selected.id}/scan-devices`,
        { method: "POST", body: JSON.stringify({ name: newDeviceName, expires_in_days: Number(newDeviceDays) || 14 }) }
      );
      setGeneratedToken({ name: result.name, token: result.token, expires_at: result.expires_at });
      setNewDeviceName("Gate scanner");
    }, "Scan device authorized. Copy the token below for device setup.");
  }

  async function revokeDevice(deviceId: string) {
    if (!selected || !window.confirm("Revoke this scanner token? The device will immediately lose offline sync authorization.")) return;
    await runAction(async () => {
      await api(`${base}/${selected.id}/scan-devices/${deviceId}`, { method: "DELETE" });
    }, "Scan device authorization revoked.");
  }

  async function resolveConflict(conflictId: string, action: "accept" | "ignore") {
    if (!selected) return;
    const note = conflictNotes[conflictId]?.trim() || (action === "accept" ? "Accepted by organizer" : "Ignored by organizer");
    await runAction(async () => {
      await api(`${base}/${selected.id}/attendance/conflicts/${conflictId}/resolve`, {
        method: "POST", body: JSON.stringify({ action, note }),
      });
    }, action === "accept" ? "Scan accepted and recorded in attendance." : "Scan ignored.");
  }

  async function manualCheckIn(registrationId: string) {
    if (!selected) return;
    await runAction(async () => {
      await api(`${base}/${selected.id}/registrations/${registrationId}/manual-check-in`, {
        method: "POST", body: "{}",
      });
    }, "Attendee checked in.");
  }

  function exportRegistrations() {
    const headings = ["Name", "Email", "Registration status", "Ticket type", "Ticket status", "Registered at", "Checked in at"];
    const lines = [headings, ...visibleRegistrations.map((row) => [row.full_name, row.email, row.status, row.ticket_type, row.ticket_status, row.registered_at, row.checked_in_at])]
      .map((line) => line.map(csvCell).join(",")).join("\r\n");
    const url = URL.createObjectURL(new Blob([`\uFEFF${lines}`], { type: "text/csv;charset=utf-8" }));
    const anchor = document.createElement("a"); anchor.href = url;
    anchor.download = `${(selected?.title ?? "event").toLowerCase().replace(/[^a-z0-9]+/g, "-")}-registrations.csv`;
    anchor.click(); URL.revokeObjectURL(url);
  }

  return <main className="meeting-shell organizer-dashboard">
    <header className="meeting-header">
      <a className="brand" href="#top"><span className="brand-mark"><span /></span><span>evenspace</span></a>
      <div className="meeting-user">
        <span className="current-nav-pill">Events</span>
        <button className="meeting-link" type="button" onClick={onMeetings}>Meetings</button>
        <button className="meeting-link" type="button" onClick={onGate}>Gate scanner</button>
        {onParticipant && <button className="meeting-link" type="button" onClick={onParticipant}>My tickets</button>}
      </div>
    </header>

    <section className="meeting-welcome">
      <span className="meeting-kicker"><CalendarDays size={15} /> EVENT ORGANIZER</span>
      <h1>Make it happen, <em>see it grow.</em></h1>
      <p>Create and publish events, manage registration capacity, authorize offline scanners, and review attendance.</p>
    </section>

    {message && <div className={`notice ${error ? "notice-error" : "notice-info"}`} role={error ? "alert" : "status"}>
      <span style={{ flex: 1 }}>{message}</span>
      <button className="icon-button notice-close" type="button" aria-label="Dismiss" onClick={() => { setMessage(""); setError(false); }}>×</button>
    </div>}

    <section className="meeting-card workspace-bar">
      <label className="field">
        <span>Workspace</span>
        <select value={workspaceId} onChange={(event) => changeWorkspace(event.target.value)}>
          {workspaces.map((row) => <option key={row.id} value={row.id}>{row.name} · {row.role.replaceAll("_", " ")}</option>)}
        </select>
      </label>
      <button className="button button-secondary" type="button" disabled={loading || busy} onClick={() => void reloadEvents().catch((reason) => { setError(true); setMessage(reason.message); })}>
        <RefreshCw size={15} /> Refresh
      </button>
    </section>

    <section className="stats-grid organizer-stats" aria-label="Workspace event summary">
      <div className="stat-card"><span>Events</span><strong>{events.length}</strong><small>in this workspace</small></div>
      <div className="stat-card"><span>Registrations</span><strong>{totals.registrations}</strong><small>{totals.capacity ? `of ${totals.capacity} total places` : "across all events"}</small></div>
      <div className="stat-card"><span>Upcoming</span><strong>{totals.upcoming}</strong><small>published events</small></div>
    </section>

    <div className="organizer-grid">
      <section className="meeting-card organizer-event-list" id="event-list">
        <div className="meeting-section-title"><div><h2>Events</h2><p>Choose an event to manage</p></div></div>
        {events.map((row) => (
          <button className={`meeting-list-item ${selectedId === row.id ? "selected" : ""}`} type="button" key={row.id} onClick={() => setSelectedId(row.id)}>
            <strong>{row.title}</strong>
            <span>{new Date(row.start_at).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })} · {row.status.replaceAll("_", " ")}</span>
            <span>{row.registration_count}{row.capacity ? ` / ${row.capacity}` : ""} registrations</span>
          </button>
        ))}
        {!events.length && !loading && <p className="meeting-empty">No events in this workspace yet.</p>}
      </section>

      <div className="organizer-main">
        {canManage && <section className="meeting-card">
          <div className="meeting-section-title"><div><h2>Create an event</h2><p>Set schedule and admission capacity</p></div></div>
          <form className="organizer-create-form" onSubmit={(event) => void createEvent(event)}>
            <label className="field"><span>Event title</span><input required maxLength={200} value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Annual community forum" /></label>
            <label className="field"><span>Category</span><input required maxLength={80} value={category} onChange={(event) => setCategory(event.target.value)} /></label>
            <label className="field organizer-wide"><span>Description</span><textarea rows={2} maxLength={10000} value={description} onChange={(event) => setDescription(event.target.value)} /></label>
            <label className="field"><span>Starts</span><input required type="datetime-local" value={startsAt} onChange={(event) => setStartsAt(event.target.value)} /></label>
            <label className="field"><span>Ends</span><input required type="datetime-local" value={endsAt} onChange={(event) => setEndsAt(event.target.value)} /></label>
            <label className="field"><span>Registration capacity</span><input type="number" min={1} value={capacity} onChange={(event) => setCapacity(event.target.value)} placeholder="Unlimited" /></label>
            <label className="field"><span>Visibility</span><select value={visibility} onChange={(event) => setVisibility(event.target.value)}><option value="public">Public</option><option value="private">Private</option></select></label>
            <button className="button button-primary organizer-wide" disabled={busy || !workspaceId}><Plus size={15} /> Create event</button>
          </form>
        </section>}

        {selected && <section className="meeting-card organizer-event-detail">
          <div className="meeting-section-title">
            <div>
              <span className="meeting-kicker">{selected.status.toUpperCase()} · {selected.visibility.toUpperCase()}</span>
              <h2>{selected.title}</h2>
              <p>{new Date(selected.start_at).toLocaleString([], { dateStyle: "full", timeStyle: "short" })} · {selected.timezone}</p>
            </div>
            <div className="record-actions">
              {canManage && selected.status === "draft" && <button className="button button-primary" disabled={busy || !selected.ticket_types.length} title={!selected.ticket_types.length ? "Add a ticket type before publishing" : undefined} onClick={() => void runAction(() => api(`${base}/${selected.id}/publish`, { method: "POST", body: "{}" }), "Event published.")}>Publish</button>}
              {canManage && selected.status === "published" && <button className="button button-primary" disabled={busy} onClick={() => void runAction(() => api(`${base}/${selected.id}/start`, { method: "POST", body: "{}" }), "Event started.")}>Start event</button>}
              {canManage && ["draft", "published"].includes(selected.status) && <button className="meeting-remove" disabled={busy} onClick={() => void cancelSelected()}>Cancel event</button>}
            </div>
          </div>

          <div className="organizer-event-kpis">
            <span><Users size={15} /> {selected.registration_count}{selected.capacity ? ` / ${selected.capacity}` : ""} registered</span>
            <span><CheckCircle2 size={15} /> {checkedInCount} checked in ({attendanceRate}%)</span>
            <span><Ticket size={15} /> {selected.ticket_types.length} ticket types</span>
          </div>

          {selected.visibility === "public" && selected.status === "published" && <p className="field-help">This event is discoverable on the participant page. Attendees can register for free admission.</p>}

          <div className="meeting-section-title"><div><h3>Ticket types</h3><p>Free admissions are ready for registration</p></div></div>
          <div className="meeting-record-list">
            {selected.ticket_types.map((item) => (
              <article className="meeting-record" key={item.id}>
                <div>
                  <strong>{item.name}</strong>
                  <small>{item.registration_count}{item.capacity ? ` / ${item.capacity}` : ""} allocated · {Number(item.price) === 0 ? "Free" : `KES ${item.price}`}</small>
                </div>
              </article>
            ))}
            {!selected.ticket_types.length && <p className="meeting-empty">Add a ticket type before publishing this event.</p>}
          </div>

          {canManage && <form className="meeting-inline-form organizer-ticket-form" onSubmit={(event) => void addTicket(event)}>
            <label className="field"><span>New free ticket type</span><input required maxLength={120} value={ticketName} onChange={(event) => setTicketName(event.target.value)} placeholder="General admission" /></label>
            <label className="field"><span>Ticket capacity</span><input type="number" min={1} value={ticketCapacity} onChange={(event) => setTicketCapacity(event.target.value)} placeholder="Use event capacity" /></label>
            <button className="button button-secondary" disabled={busy}><Plus size={15} /> Add ticket</button>
          </form>}
        </section>}

        {selected && canManage && (
          <section className="meeting-card organizer-scanners" id="event-scanners">
            <div className="meeting-section-title">
              <div>
                <h2>Gate scanners & offline access</h2>
                <p>Authorize devices to cache the admission list and validate tickets offline</p>
              </div>
            </div>

            {generatedToken && (
              <div className="notice notice-success" role="status">
                <KeyRound size={18} />
                <div style={{ flex: 1 }}>
                  <strong>Scanner authorized for "{generatedToken.name}"</strong>
                  <p style={{ margin: "4px 0", fontSize: "0.85rem" }}>One-time scanner token (expires {new Date(generatedToken.expires_at).toLocaleDateString()}):</p>
                  <code style={{ display: "block", wordBreak: "break-all", background: "rgba(0,0,0,0.06)", padding: "6px 8px", borderRadius: "4px" }}>
                    {generatedToken.token}
                  </code>
                  <div style={{ display: "flex", gap: "8px", marginTop: "8px" }}>
                    <button className="button button-secondary" type="button" onClick={() => void navigator.clipboard.writeText(generatedToken.token).then(() => setMessage("Scanner token copied."))}>
                      <Copy size={14} /> Copy token
                    </button>
                    {onOpenScanner && (
                      <button className="button button-primary" type="button" onClick={() => onOpenScanner(selected.id, generatedToken.token)}>
                        <ExternalLink size={14} /> Open in scanner
                      </button>
                    )}
                  </div>
                </div>
              </div>
            )}

            <form className="meeting-inline-form" onSubmit={(e) => void createScanDevice(e)}>
              <label className="field"><span>Scanner name</span><input required maxLength={80} value={newDeviceName} onChange={(e) => setNewDeviceName(e.target.value)} placeholder="e.g. Main Gate Scanner" /></label>
              <label className="field"><span>Valid for (days)</span><input required type="number" min={1} max={30} value={newDeviceDays} onChange={(e) => setNewDeviceDays(e.target.value)} /></label>
              <button className="button button-secondary" disabled={busy}><Smartphone size={15} /> Authorize device</button>
            </form>

            <div className="organizer-table-scroll" style={{ marginTop: "16px" }}>
              <table className="organizer-table">
                <thead><tr><th>Device</th><th>Status</th><th>Expires</th><th>Action</th></tr></thead>
                <tbody>
                  {devices.map((device) => (
                    <tr key={device.id}>
                      <td><strong>{device.name}</strong><small>ID: {device.id.slice(0, 8)}…</small></td>
                      <td>
                        <span className={`status-pill ${device.is_active ? "status-published" : "status-draft"}`}>
                          {device.is_active ? "Active" : device.revoked_at ? "Revoked" : "Expired"}
                        </span>
                      </td>
                      <td>{new Date(device.expires_at).toLocaleDateString()}</td>
                      <td>
                        {device.is_active && (
                          <button className="text-button meeting-remove" type="button" disabled={busy} onClick={() => void revokeDevice(device.id)}>
                            <Trash2 size={13} /> Revoke
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                  {!devices.length && <tr><td colSpan={4} className="meeting-empty">No scanner devices authorized yet.</td></tr>}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {selected && canManage && (
          <section className="meeting-card organizer-conflicts">
            <div className="meeting-section-title">
              <div>
                <h2>Offline scan conflicts {pendingConflictsCount > 0 && <span className="conflict-badge">{pendingConflictsCount}</span>}</h2>
                <p>Review scans submitted by offline devices that require organizer adjudication</p>
              </div>
              <button type="button" className="button button-secondary" onClick={() => void reloadConflicts()}>
                <RefreshCw size={14} /> Refresh
              </button>
            </div>

            {pendingConflictsCount > 0 && (
              <div className="notice notice-warning" role="alert">
                <ShieldAlert size={18} />
                <span>{pendingConflictsCount} scan conflict(s) are waiting for your review. Attendees may have registered after the device downloaded its ticket snapshot.</span>
              </div>
            )}

            <div className="organizer-table-scroll">
              <table className="organizer-table">
                <thead><tr><th>Attendee / Ticket</th><th>Reason</th><th>Scanned at</th><th>Resolution</th></tr></thead>
                <tbody>
                  {conflicts.map((c) => (
                    <tr key={c.id}>
                      <td>
                        <strong>{c.attendee_name || "Unknown attendee"}</strong>
                        <small>Ticket: {c.ticket_id ? c.ticket_id.slice(0, 8) + "…" : "Unmatched credential"}</small>
                      </td>
                      <td>
                        <span className="status-pill status-draft">{c.reason.replaceAll("_", " ")}</span>
                      </td>
                      <td>{new Date(c.scanned_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}</td>
                      <td>
                        {c.status === "conflict" ? (
                          <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                            <input
                              className="conflict-note-input"
                              placeholder="Optional note"
                              value={conflictNotes[c.id] || ""}
                              onChange={(e) => setConflictNotes({ ...conflictNotes, [c.id]: e.target.value })}
                            />
                            <div style={{ display: "flex", gap: "6px" }}>
                              <button className="button button-primary" style={{ padding: "4px 8px", fontSize: "0.8rem" }} type="button" disabled={busy} onClick={() => void resolveConflict(c.id, "accept")}>
                                Accept
                              </button>
                              <button className="button button-secondary" style={{ padding: "4px 8px", fontSize: "0.8rem" }} type="button" disabled={busy} onClick={() => void resolveConflict(c.id, "ignore")}>
                                Ignore
                              </button>
                            </div>
                          </div>
                        ) : (
                          <span style={{ fontSize: "0.85rem", color: "var(--muted)" }}>
                            Resolved ({c.status}) {c.resolution_note && `· ${c.resolution_note}`}
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                  {!conflicts.length && <tr><td colSpan={4} className="meeting-empty">No sync conflicts recorded for this event.</td></tr>}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {selected && canManage && (
          <section className="meeting-card" id="event-registrations">
            <div className="meeting-section-title">
              <div>
                <h2>Registrations & attendance</h2>
                <p>{registrations.length} records · {checkedInCount} checked in</p>
              </div>
              <button type="button" className="button button-secondary" onClick={() => void reloadRegistrations().catch((reason) => { setError(true); setMessage(reason.message); })}>
                <RefreshCw size={14} /> Refresh
              </button>
            </div>

            <label className="field organizer-search">
              <span>Find an attendee</span>
              <div className="organizer-search-box">
                <Search size={15} />
                <input type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search by name, email, or ticket" />
              </div>
            </label>

            <div className="organizer-registration-heading">
              <span>{visibleRegistrations.length} shown</span>
              <button className="meeting-link" type="button" disabled={!visibleRegistrations.length} onClick={exportRegistrations}>
                <Download size={14} /> Export CSV
              </button>
            </div>

            <div className="organizer-table-scroll">
              <table className="organizer-table">
                <thead><tr><th>Attendee</th><th>Ticket</th><th>Registration</th><th>Check-in</th></tr></thead>
                <tbody>
                  {visibleRegistrations.map((row) => (
                    <tr key={row.id}>
                      <td><strong>{row.full_name}</strong><small>{row.email}</small></td>
                      <td>{row.ticket_type}<small>{row.ticket_status ?? "No ticket issued"}</small></td>
                      <td>{row.status}</td>
                      <td>
                        {row.checked_in_at ? (
                          <span style={{ color: "var(--success, #16a34a)", fontWeight: 500 }}>
                            {new Date(row.checked_in_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}
                          </span>
                        ) : row.status === "confirmed" ? (
                          <button
                            className="button button-secondary"
                            style={{ padding: "3px 8px", fontSize: "0.8rem" }}
                            type="button"
                            disabled={busy || selected.status !== "in_progress"}
                            title={selected.status !== "in_progress" ? "Start the event to begin check-in" : undefined}
                            onClick={() => void manualCheckIn(row.id)}
                          >
                            Check in
                          </button>
                        ) : (
                          "Pending"
                        )}
                      </td>
                    </tr>
                  ))}
                  {!visibleRegistrations.length && <tr><td colSpan={4} className="meeting-empty">{registrations.length ? "No registrations match the search." : "Registrations will appear here as people sign up."}</td></tr>}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {!canManage && workspaceId && (
          <section className="meeting-card">
            <p className="meeting-message">You can view events in this workspace. Ask an owner or administrator for Event Manager access to manage events and attendee records.</p>
          </section>
        )}
      </div>
    </div>
    <footer className="footer"><span>EVENSPACE</span><span>Event registration & attendance overview</span></footer>
  </main>;
}
