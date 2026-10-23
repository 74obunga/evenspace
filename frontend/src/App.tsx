import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import type { IScannerControls } from "@zxing/browser";
import {
  AlertCircle, ArrowDownToLine, Camera, Check, CheckCircle2, Clock3, CloudOff,
  CloudUpload, LockKeyhole, QrCode, RefreshCw, ShieldCheck, Smartphone, TicketCheck, Wifi,
} from "lucide-react";
import {
  deleteBatch, forgetSession, getBatches, getScans, getSession, getSessions, saveBatch, saveScan, saveSession,
  type CachedSession, type LocalScan, type PendingBatch, type SyncPayload,
} from "./offlineDb";
import Meetings from "./Meetings";
import Participant from "./Participant";
import MeetingJoin from "./MeetingJoin";
import PasswordReset from "./PasswordReset";
import EmailVerification from "./EmailVerification";
import InvitationAccept from "./InvitationAccept";
import OrganizerDashboard from "./OrganizerDashboard";
import { API_BASE } from "./apiBase";

const CREDENTIAL_PATTERN = /^[0-9a-f]{64}$/;

function hashHex(value: string): Promise<string> {
  return crypto.subtle.digest("SHA-256", new TextEncoder().encode(value)).then((buffer) =>
    Array.from(new Uint8Array(buffer), (byte) => byte.toString(16).padStart(2, "0")).join(""),
  );
}

function formatTime(value: string): string {
  return new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" }).format(new Date(value));
}

function App() {
  const [view, setView] = useState<"scanner" | "meetings" | "events" | "participant">("scanner");
  const [sessions, setSessions] = useState<CachedSession[]>([]);
  const [session, setSession] = useState<CachedSession | null>(null);
  const [eventId, setEventId] = useState("");
  const [deviceToken, setDeviceToken] = useState("");
  const [scans, setScans] = useState<LocalScan[]>([]);
  const [online, setOnline] = useState(navigator.onLine);
  const [credential, setCredential] = useState("");
  const [busy, setBusy] = useState(false);
  const [cameraActive, setCameraActive] = useState(false);
  const [notice, setNotice] = useState<{ tone: "success" | "warning" | "error" | "info"; text: string } | null>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const controlsRef = useRef<IScannerControls | null>(null);

  const reloadLocal = useCallback(async (id: string) => {
    const [stored, storedScans] = await Promise.all([getSession(id), getScans(id)]);
    setSession(stored ?? null);
    setScans(storedScans.sort((a, b) => b.scannedAt.localeCompare(a.scannedAt)));
    if (stored) {
      setEventId(stored.eventId);
      setDeviceToken(stored.deviceToken);
    }
    return stored;
  }, []);

  const refreshSessions = useCallback(async () => {
    const stored: CachedSession[] = await getSessions();
    setSessions(stored.sort((a, b) => a.eventTitle.localeCompare(b.eventTitle)));
    return stored;
  }, []);

  useEffect(() => {
    void refreshSessions().then((stored) => {
      if (stored.length === 1) void reloadLocal(stored[0].eventId);
    });
    const onlineChanged = () => setOnline(navigator.onLine);
    window.addEventListener("online", onlineChanged);
    window.addEventListener("offline", onlineChanged);
    return () => {
      window.removeEventListener("online", onlineChanged);
      window.removeEventListener("offline", onlineChanged);
    };
  }, [refreshSessions, reloadLocal]);

  useEffect(() => () => controlsRef.current?.stop(), []);

  useEffect(() => {
    if (!cameraActive || !session || !videoRef.current) return;
    let mounted = true;
    void import("@zxing/browser").then(({ BrowserQRCodeReader }) => {
      if (!mounted || !videoRef.current) return;
      const reader = new BrowserQRCodeReader();
      return reader.decodeFromVideoDevice(undefined, videoRef.current, (result) => {
        if (!result || !mounted) return;
        controlsRef.current?.stop();
        controlsRef.current = null;
        setCameraActive(false);
        void recordCredential(result.getText());
      }).then((controls) => {
        if (!mounted) controls.stop();
        else controlsRef.current = controls;
      });
    }).catch(() => {
      if (!mounted) return;
      setCameraActive(false);
      setNotice({ tone: "error", text: "Camera access failed. Allow camera access or enter the ticket code manually." });
    });
    return () => {
      mounted = false;
      controlsRef.current?.stop();
      controlsRef.current = null;
    };
  }, [cameraActive, session]);

  const pendingCount = useMemo(() => scans.filter((scan) => scan.status === "pending").length, [scans]);
  const acceptedCount = useMemo(() => scans.filter((scan) => scan.status === "accepted").length, [scans]);
  const conflictCount = useMemo(() => scans.filter((scan) => scan.status === "conflict").length, [scans]);

  const meetingJoin = window.location.hash.match(/^#join-meeting\/([0-9a-f-]{36})\/([A-Za-z0-9_-]{32,})$/i);
  if (meetingJoin) return <MeetingJoin meetingId={meetingJoin[1]} token={meetingJoin[2]} />;
  const passwordReset = window.location.hash.match(/^#reset-password\/([A-Za-z0-9_-]{32,})$/);
  if (passwordReset) return <PasswordReset token={passwordReset[1]} onDone={() => { window.location.hash = ""; setView("meetings"); }} />;
  const emailVerification = window.location.hash.match(/^#verify-email\/([A-Za-z0-9_-]{32,})$/);
  if (emailVerification) return <EmailVerification token={emailVerification[1]} onDone={() => { window.location.hash = ""; setView("meetings"); }} />;
  const invitation = window.location.hash.match(/^#accept-invitation\/([A-Za-z0-9_-]{32,})$/);
  if (invitation) return <InvitationAccept token={invitation[1]} onDone={() => { window.location.hash = ""; setView("meetings"); }} />;
  if (view === "events") return <OrganizerDashboard onMeetings={() => setView("meetings")} onGate={() => setView("scanner")} onParticipant={() => setView("participant")} onOpenScanner={(id, token) => { setEventId(id); setDeviceToken(token); setView("scanner"); }} />;
  if (view === "meetings") return <Meetings onGate={() => setView("scanner")} onEvents={() => setView("events")} onParticipant={() => setView("participant")} />;
  if (view === "participant") return <Participant onGate={() => setView("scanner")} onEvents={() => setView("events")} onMeetings={() => setView("meetings")} />;

  async function connectToEvent(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const id = eventId.trim();
    const token = deviceToken.trim();
    if (!id || !token) {
      setNotice({ tone: "warning", text: "Enter the event ID and scanner token to download its authorized ticket list." });
      return;
    }
    setBusy(true);
    setNotice(null);
    try {
      const response = await fetch(`${API_BASE}/events/${encodeURIComponent(id)}/attendance/offline-manifest`, {
        headers: { "X-Scan-Device-Token": token },
      });
      if (!response.ok) throw new Error(response.status === 401 ? "This scanner token is invalid, expired, or revoked." : `Could not load the event list (${response.status}).`);
      const manifest = await response.json() as {
        event_id: string; event_title: string; starts_at: string; snapshot_id: string;
        generated_at: string; tickets: CachedSession["tickets"];
      };
      const next: CachedSession = {
        eventId: manifest.event_id, deviceToken: token, snapshotId: manifest.snapshot_id,
        generatedAt: manifest.generated_at, eventTitle: manifest.event_title,
        startsAt: manifest.starts_at, tickets: manifest.tickets,
      };
      await saveSession(next);
      await refreshSessions();
      await reloadLocal(next.eventId);
      setNotice({ tone: "success", text: `Ticket list saved on this device · ${next.tickets.length} tickets available offline.` });
    } catch (error) {
      setNotice({ tone: "error", text: error instanceof Error ? error.message : "Could not connect to the event." });
    } finally {
      setBusy(false);
    }
  }

  async function chooseSavedEvent(id: string) {
    setEventId(id);
    await reloadLocal(id);
    setNotice(null);
  }

  async function recordCredential(rawValue: string) {
    const value = rawValue.trim();
    if (!session) return;
    if (!CREDENTIAL_PATTERN.test(value)) {
      setNotice({ tone: "warning", text: "That code is not a valid EvenSpace ticket QR. No scan was recorded." });
      return;
    }
    const credentialHash = await hashHex(value);
    const ticket = session.tickets.find((item) => item.credential_hash === credentialHash);
    const scan: LocalScan = {
      scanEventId: crypto.randomUUID(), eventId: session.eventId, snapshotId: session.snapshotId,
      credential: value, credentialHash, scannedAt: new Date().toISOString(), status: "pending",
      attendeeName: ticket?.attendee_name,
      localValidation: ticket ? (ticket.status === "active" ? "recognized" : "revoked") : "not_in_snapshot",
    };
    await saveScan(scan);
    await reloadLocal(session.eventId);
    setCredential("");
    if (scan.localValidation === "recognized") {
      setNotice({ tone: "success", text: `${scan.attendeeName ?? "Ticket"} is on this device's ticket list. Scan queued for synchronization.` });
    } else if (scan.localValidation === "revoked") {
      setNotice({ tone: "warning", text: "This ticket was revoked in the saved list. Scan evidence was queued for organizer review." });
    } else {
      setNotice({ tone: "warning", text: "This ticket is not in the saved list. Scan evidence was kept for conflict review after sync." });
    }
  }

  async function submitManualScan(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await recordCredential(credential);
  }

  function startCamera() {
    if (!session) return;
    setNotice(null);
    setCameraActive(true);
  }

  function stopCamera() {
    controlsRef.current?.stop();
    controlsRef.current = null;
    setCameraActive(false);
  }

  async function synchronize() {
    if (!session || !online || busy) return;
    setBusy(true);
    setNotice(null);
    try {
      const savedBatches = (await getBatches(session.eventId)).sort((a, b) => a.createdAt.localeCompare(b.createdAt));
      let batch: PendingBatch | undefined = savedBatches[0];
      if (!batch) {
        const pending = (await getScans(session.eventId))
          .filter((scan) => scan.status === "pending" && scan.snapshotId === session.snapshotId)
          .sort((a, b) => a.scannedAt.localeCompare(b.scannedAt))
          .slice(0, 500);
        if (!pending.length) {
          setNotice({ tone: "info", text: "There are no queued scans for this ticket list." });
          return;
        }
        const batchId = crypto.randomUUID();
        const payload: SyncPayload = {
          batch_id: batchId,
          snapshot_id: session.snapshotId,
          scans: pending.map((scan) => ({
            scan_event_id: scan.scanEventId, credential: scan.credential, scanned_at: scan.scannedAt,
          })),
        };
        batch = {
          batchId, eventId: session.eventId, snapshotId: session.snapshotId,
          scanIds: pending.map((scan) => scan.scanEventId), payload, createdAt: new Date().toISOString(),
        };
        // Keep the exact request until the server acknowledges it; after a lost response, retry the same batch ID and bytes.
        await saveBatch(batch);
      }
      const response = await fetch(`${API_BASE}/events/${encodeURIComponent(session.eventId)}/attendance/sync`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Scan-Device-Token": session.deviceToken },
        body: JSON.stringify(batch.payload),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null) as { detail?: string } | null;
        throw new Error(body?.detail ?? `Sync failed (${response.status}). The batch remains saved for retry.`);
      }
      const result = await response.json() as {
        outcomes: Array<{ scan_event_id: string; status: "accepted" | "duplicate" | "conflict"; reason?: string; conflict_id?: string }>;
      };
      const byId = new Map(result.outcomes.map((outcome) => [outcome.scan_event_id, outcome]));
      if (batch.scanIds.some((id) => !byId.has(id))) {
        throw new Error("The server response did not include every scan. The original batch is saved for a safe retry.");
      }
      const localScans = await getScans(session.eventId);
      const localById = new Map(localScans.map((scan) => [scan.scanEventId, scan]));
      for (const id of batch.scanIds) {
        const outcome = byId.get(id);
        const local = localById.get(id);
        if (!local || !outcome) continue;
        await saveScan({
          ...local, credential: "", status: outcome.status,
          reason: outcome.reason, conflictId: outcome.conflict_id,
        });
      }
      await deleteBatch(batch.batchId);
      await reloadLocal(session.eventId);
      const conflicts = result.outcomes.filter((outcome) => outcome.status === "conflict").length;
      setNotice({ tone: conflicts ? "warning" : "success", text: conflicts
        ? `Sync complete. ${conflicts} scan${conflicts === 1 ? "" : "s"} need organizer review.`
        : `Sync complete. ${result.outcomes.length} scan${result.outcomes.length === 1 ? "" : "s"} recorded.` });
    } catch (error) {
      setNotice({ tone: "error", text: error instanceof Error ? error.message : "Sync failed. The queued batch is still saved." });
    } finally {
      setBusy(false);
    }
  }

  async function forgetCurrentEvent() {
    if (!session || !window.confirm("Remove this event's saved list and scan history from this device?")) return;
    try {
      await forgetSession(session.eventId);
      const stored = await refreshSessions();
      setSession(null);
      setScans([]);
      setEventId("");
      setDeviceToken("");
      setNotice({ tone: "success", text: "Event data removed from this device." });
      if (stored.length === 1) await reloadLocal(stored[0].eventId);
    } catch (error) {
      setNotice({ tone: "warning", text: error instanceof Error ? error.message : "Could not remove local event data." });
    }
  }

  return (
    <main className="shell">
      <header className="topbar">
        <a className="brand" href="#top" aria-label="EvenSpace home">
          <span className="brand-mark"><span /></span>
          <span>evenspace</span>
        </a>
        <div className="topbar-actions">
          <button className="view-switch" type="button" onClick={() => setView("events")}>Events</button>
          <button className="view-switch" type="button" onClick={() => setView("meetings")}>Meetings</button>
          <button className="view-switch" type="button" onClick={() => setView("participant")}>My tickets</button>
          <div className={`connection ${online ? "is-online" : "is-offline"}`} role="status">
            {online ? <Wifi size={15} /> : <CloudOff size={15} />}
            <span>{online ? "Online" : "Offline mode"}</span>
          </div>
        </div>
      </header>

      <section className="intro" id="top">
        <div className="eyebrow"><span className="eyebrow-dot" /> GATE OPERATIONS</div>
        <h1>Check in, <span>anywhere.</span></h1>
        <p>Scan tickets at the gate. Your scans stay on this device until they’re safely synced.</p>
      </section>

      {notice && <div className={`notice notice-${notice.tone}`} role={notice.tone === "error" ? "alert" : "status"}>
        {notice.tone === "success" ? <CheckCircle2 size={18} /> : notice.tone === "error" ? <AlertCircle size={18} /> : <ShieldCheck size={18} />}
        <span>{notice.text}</span>
        <button className="icon-button notice-close" type="button" aria-label="Dismiss message" onClick={() => setNotice(null)}>×</button>
      </div>}

      {!session ? (
        <section className="connect-card card">
          <div className="section-heading">
            <div className="heading-icon"><Smartphone size={20} /></div>
            <div><h2>Connect a scanner</h2><p>Download an event’s ticket list for this device.</p></div>
          </div>
          {sessions.length > 0 && <label className="field">
            <span>Saved events on this device</span>
            <select value="" onChange={(event) => void chooseSavedEvent(event.target.value)}>
              <option value="">Choose an event to scan offline</option>
              {sessions.map((saved) => <option key={saved.eventId} value={saved.eventId}>{saved.eventTitle}</option>)}
            </select>
          </label>}
          <form className="connect-form" onSubmit={(event) => void connectToEvent(event)}>
            <label className="field">
              <span>Event ID</span>
              <input value={eventId} onChange={(event) => setEventId(event.target.value)} placeholder="Paste the event ID" autoComplete="off" />
            </label>
            <label className="field">
              <span>Scanner token</span>
              <input value={deviceToken} onChange={(event) => setDeviceToken(event.target.value)} placeholder="Paste the one-time scanner token" autoComplete="off" />
            </label>
            <button className="button button-primary full-width" disabled={busy || !online} type="submit">
              <ArrowDownToLine size={17} /> {busy ? "Downloading ticket list…" : "Download event list"}
            </button>
            {!online && <p className="field-help">Reconnect to the internet to download or refresh an event list.</p>}
          </form>
          <div className="security-note"><LockKeyhole size={16} /><span>Event data and unsynced ticket codes are stored in this browser’s local database.</span></div>
        </section>
      ) : (
        <>
          <section className="event-card card">
            <div className="event-topline">
              <span className="event-label"><TicketCheck size={15} /> ACTIVE EVENT</span>
              <button className="text-button" type="button" onClick={() => void forgetCurrentEvent()}>Remove from device</button>
            </div>
            <h2>{session.eventTitle}</h2>
            <div className="event-meta"><span><Clock3 size={15} /> {new Date(session.startsAt).toLocaleString()}</span>
              <span><ShieldCheck size={15} /> List downloaded {formatTime(session.generatedAt)}</span></div>
          </section>

          <section className="stats-grid" aria-label="Scan summary">
            <div className="stat-card"><span>Queued</span><strong>{pendingCount}</strong><small>waiting to sync</small></div>
            <div className="stat-card"><span>Synced</span><strong>{acceptedCount}</strong><small>admissions recorded</small></div>
            <div className="stat-card"><span>Review</span><strong>{conflictCount}</strong><small>organizer follow-up</small></div>
          </section>

          <section className="scanner-card card">
            <div className="section-heading">
              <div className="heading-icon scan-icon"><QrCode size={20} /></div>
              <div><h2>Scan a ticket</h2><p>Camera access requires a secure connection or localhost.</p></div>
            </div>
            {cameraActive && <div className="camera-frame"><video ref={videoRef} muted playsInline aria-label="Camera QR preview" />
              <div className="scan-brackets" aria-hidden="true"><i /><i /><i /><i /></div>
              <button className="button button-secondary stop-camera" type="button" onClick={stopCamera}>Stop camera</button>
            </div>}
            {!cameraActive && <button className="camera-button" type="button" onClick={() => void startCamera()}>
              <span><Camera size={21} /></span><strong>Open camera</strong><small>Point at a ticket QR code</small>
            </button>}
            <div className="divider"><span>OR ENTER CODE</span></div>
            <form className="manual-form" onSubmit={(event) => void submitManualScan(event)}>
              <label className="sr-only" htmlFor="ticket-code">64-character ticket code</label>
              <input id="ticket-code" value={credential} onChange={(event) => setCredential(event.target.value)}
                placeholder="Enter ticket code" autoComplete="off" autoCapitalize="off" spellCheck={false} maxLength={64} />
              <button className="button button-primary" type="submit" disabled={!credential.trim()}><Check size={17} /> Check in</button>
            </form>
            <p className="field-help">Scans are recorded locally first. Tickets missing from this saved list are kept for organizer review.</p>
          </section>

          <section className="sync-panel">
            <div className="sync-copy"><div className="sync-symbol"><CloudUpload size={19} /></div>
              <div><strong>{pendingCount ? `${pendingCount} scan${pendingCount === 1 ? "" : "s"} ready to sync` : "All caught up"}</strong>
                <span>{online ? "Sync when you have a connection." : "Your scans are safe on this device."}</span></div></div>
            <button className="button button-primary sync-button" type="button" onClick={() => void synchronize()}
              disabled={!online || !pendingCount || busy}>
              <RefreshCw size={16} className={busy ? "spin" : ""} /> {busy ? "Syncing…" : "Sync scans"}
            </button>
          </section>

          <section className="scan-history">
            <div className="history-heading"><div><h2>Recent scans</h2><p>Most recent scans on this device</p></div>
              <span className="history-count">{scans.length}</span></div>
            {scans.length === 0 ? <div className="empty-state"><QrCode size={23} /><p>No scans yet. Scan a ticket to get started.</p></div> :
              <div className="scan-list">{scans.slice(0, 30).map((scan) => <ScanRow key={scan.scanEventId} scan={scan} />)}</div>}
          </section>
        </>
      )}
      <footer className="footer"><span>EVENSPACE</span><span>Offline-ready gate check-in</span></footer>
    </main>
  );
}

function ScanRow({ scan }: { scan: LocalScan }) {
  const label = scan.status === "pending" ? "Queued" : scan.status === "accepted" ? "Synced" : scan.status === "duplicate" ? "Already checked in" : "Review needed";
  const sublabel = scan.status === "conflict" ? (scan.reason ?? "Organizer review required").replaceAll("_", " ") :
    scan.status === "pending" ? (scan.localValidation === "recognized" ? "Ticket found in saved list" : scan.localValidation === "revoked" ? "Revoked in saved list · review after sync" : "Not on saved list · review after sync") :
    scan.status === "accepted" ? "Admission recorded" : "Existing admission returned";
  return <article className="scan-row">
    <span className={`scan-status-dot status-${scan.status}`} aria-hidden="true" />
    <div className="scan-person"><strong>{scan.attendeeName ?? "Ticket scan"}</strong><span>{sublabel}</span></div>
    <div className="scan-time"><span className={`status-pill pill-${scan.status}`}>{label}</span><time dateTime={scan.scannedAt}>{formatTime(scan.scannedAt)}</time></div>
  </article>;
}

export default App;
