import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { CalendarDays, Clipboard, Download, FileText, Link2, LogIn, Mail, MapPin, Plus, Printer, QrCode, RefreshCw, Users } from "lucide-react";
import WorkspaceInvitations from "./WorkspaceInvitations";
import OrganizerDashboard from "./OrganizerDashboard";
import NotificationTemplates from "./NotificationTemplates";
import { api } from "./api";
import { API_BASE } from "./apiBase";

function defaultMeetingTime(hour: number) {
  const date = new Date();
  date.setDate(date.getDate() + 1);
  date.setHours(hour, 0, 0, 0);
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 16);
}
type Workspace = { id: string; name: string; role: string };
type Meeting = { id: string; workspace_id: string; event_id: string; meeting_type: string; meeting_mode: "physical" | "online"; online_url: string | null; status: string; cancellation_reason: string | null; created_at: string };
type EventDetails = { id: string; title: string; start_at: string; end_at: string; timezone: string };
type Agenda = { id: string; position: number; title: string; description: string | null; duration_minutes: number | null };
type Minutes = { id: string; revision: number; content: string; status: string; approval_note: string | null };
type Decision = { id: string; decision_number: number; title: string; details: string; status: string };
type ActionItem = { id: string; title: string; details: string | null; status: string; due_at: string | null };
type Invitee = { id: string; user_id: string; attendance_status: string; attendance_note: string | null };
type Attachment = { id: string; filename: string; media_type: string; size_bytes: number; content_sha256: string };
type GuestRegistration = { id: string; meeting_id: string; full_name: string; email: string; phone: string; attendee_type: string; organization: string | null; attendance_status: string; attendance_note: string | null; registered_at: string; registration_source: "qr" | "admin"; registered_by_id: string | null; signature_present: boolean; gps_latitude: number | null; gps_longitude: number | null; gps_accuracy_m: number | null; gps_captured_at: string | null };
type MeetingSection = "overview" | "attendees" | "records" | "invitations" | "checkin";

function attendeeRoleLabel(role: string) {
  const labels: Record<string, string> = {
    speaker: "Speaker", secretary: "Secretary", chairperson: "Chairperson",
    member_delegate: "Member / Delegate", staff: "Staff", guest: "Guest",
  };
  return labels[role] ?? role;
}

export default function Meetings({
  onGate,
  onEvents,
  onParticipant,
}: {
  onGate: () => void;
  onEvents?: () => void;
  onParticipant?: () => void;
}) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [workspaceName, setWorkspaceName] = useState("");
  const [isRegister, setIsRegister] = useState(false);
  const [isForgotPassword, setIsForgotPassword] = useState(false);
  const [isResendVerification, setIsResendVerification] = useState(false);
  const [needsVerification, setNeedsVerification] = useState(false);
  const [userEmail, setUserEmail] = useState("");
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [workspaceId, setWorkspaceId] = useState("");
  const [meetings, setMeetings] = useState<Meeting[]>([]);
  const [meeting, setMeeting] = useState<Meeting | null>(null);
  const [eventDetails, setEventDetails] = useState<EventDetails | null>(null);
  const [eventTitles, setEventTitles] = useState<Record<string, string>>({});
  const [agenda, setAgenda] = useState<Agenda[]>([]);
  const [minutes, setMinutes] = useState<Minutes[]>([]);
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [actions, setActions] = useState<ActionItem[]>([]);
  const [invitees, setInvitees] = useState<Invitee[]>([]);
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [guestRegistrations, setGuestRegistrations] = useState<GuestRegistration[]>([]);
  const [meetingSection, setMeetingSection] = useState<MeetingSection>("overview");
  const [meetingSearch, setMeetingSearch] = useState("");
  const [signaturePreview, setSignaturePreview] = useState<{ attendeeId: string; url: string } | null>(null);
  const [guestJoinLink, setGuestJoinLink] = useState("");
  const [meetingTitle, setMeetingTitle] = useState("");
  const [meetingType, setMeetingType] = useState("General meeting");
  const [meetingStart, setMeetingStart] = useState(() => defaultMeetingTime(9));
  const [meetingEnd, setMeetingEnd] = useState(() => defaultMeetingTime(10));
  const [meetingMode, setMeetingMode] = useState<"physical" | "online">("physical");
  const [onlineUrl, setOnlineUrl] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [showOrganizer, setShowOrganizer] = useState(false);
  const [showEmailTemplates, setShowEmailTemplates] = useState(false);
  const activeWorkspaceId = useRef("");
  const meetingLoadVersion = useRef(0);

  useEffect(() => () => { if (signaturePreview) URL.revokeObjectURL(signaturePreview.url); }, [signaturePreview]);

  async function toggleSignaturePreview(attendeeId: string) {
    if (signaturePreview?.attendeeId === attendeeId) { setSignaturePreview(null); return; }
    if (!meeting || !workspaceId) return;
    try {
      const response = await fetch(`${API_BASE}/workspaces/${workspaceId}/meetings/${meeting.id}/guest-registrations/${attendeeId}/signature`, { credentials: "include", cache: "no-store" });
      if (!response.ok) throw new Error(response.status === 404 ? "Signature image is unavailable." : `Could not load signature (${response.status}).`);
      const url = URL.createObjectURL(await response.blob());
      setSignaturePreview({ attendeeId, url });
    } catch (error) { setMessage(error instanceof Error ? error.message : "Could not load the attendee signature."); }
  }

  function eraseAttendeePrivacyData(attendeeId: string) {
    if (!meeting || !window.confirm("Permanently remove this attendee’s saved signature and location? Their registration and attendance record will remain.")) return;
    void submit(new Event("submit") as unknown as FormEvent,
      () => api(`${base}/guest-registrations/${attendeeId}/privacy-data`, { method: "DELETE" }),
      "Saved signature and location data removed.");
    if (signaturePreview?.attendeeId === attendeeId) setSignaturePreview(null);
  }

  const reloadWorkspaces = useCallback(async () => {
    const rows = await api<Workspace[]>("/workspaces");
    setWorkspaces(rows);
    if (!workspaceId && rows.length) setWorkspaceId(rows[0].id);
  }, [workspaceId]);

  const reloadMeetings = useCallback(async (id = workspaceId) => {
    if (!id) return;
    const requestedWorkspaceId = id;
    const [meetingRows, eventRows] = await Promise.all([
      api<Meeting[]>(`/workspaces/${id}/meetings`),
      api<EventDetails[]>(`/workspaces/${id}/events`),
    ]);
    if (activeWorkspaceId.current !== requestedWorkspaceId) return;
    setMeetings(meetingRows);
    setEventTitles(Object.fromEntries(eventRows.map((event) => [event.id, event.title])));
  }, [workspaceId]);

  const reloadMeeting = useCallback(async (id: string) => {
    if (!workspaceId) return;
    const requestedWorkspaceId = workspaceId;
    const loadVersion = ++meetingLoadVersion.current;
    const root = `/workspaces/${workspaceId}/meetings/${id}`;
    const record = await api<Meeting>(root);
    const guestRowsRequest = api<GuestRegistration[]>(`${root}/guest-registrations`).catch((error) => {
      if (activeWorkspaceId.current === requestedWorkspaceId && meetingLoadVersion.current === loadVersion) {
        const reason = error instanceof Error ? error.message : "request failed";
        setMessage(`Meeting loaded, but attendee registrations could not be fetched: ${reason}`);
      }
      return [];
    });
    const [agendaRows, minuteRows, decisionRows, actionRows, inviteeRows, attachmentRows, guestRows, eventRow] = await Promise.all([
      api<Agenda[]>(`${root}/agenda`), api<Minutes[]>(`${root}/minutes`),
      api<Decision[]>(`${root}/decisions`), api<ActionItem[]>(`${root}/action-items`), api<Invitee[]>(`${root}/invitees`),
      api<Attachment[]>(`${root}/attachments`), guestRowsRequest,
      api<EventDetails>(`/workspaces/${workspaceId}/events/${record.event_id}`),
    ]);
    if (activeWorkspaceId.current !== requestedWorkspaceId || meetingLoadVersion.current !== loadVersion) return;
    setMeeting(record); setAgenda(agendaRows); setMinutes(minuteRows);
    setEventDetails(eventRow);
    setDecisions(decisionRows); setActions(actionRows); setInvitees(inviteeRows); setAttachments(attachmentRows); setGuestRegistrations(guestRows);
    await reloadMeetings();
  }, [workspaceId, reloadMeetings]);

  useEffect(() => { activeWorkspaceId.current = workspaceId; }, [workspaceId]);

  useEffect(() => {
    const applyContext = (event?: Event) => {
      const route = event instanceof CustomEvent && typeof event.detail === "string" ? event.detail : `${window.location.pathname}${window.location.hash}`;
      const parts = route.split("#")[0].split("/").filter(Boolean);
      const routeMeetingId = parts[0] === "meetings" && /^[0-9a-f-]{36}$/i.test(parts[1] ?? "") ? parts[1] : "";
      const routeSection = parts[2] === "attendees" ? "attendees" : parts[2] === "agenda" ? "records"
        : parts[2] === "attendance" ? "checkin" : parts[2] === "invitations" ? "invitations" : "";
      const hashSection = route.split("#")[1];
      const section = (routeSection || hashSection) as MeetingSection | undefined;
      if (section && ["overview", "attendees", "records", "invitations", "checkin"].includes(section)) {
        setMeetingSection(section);
        window.setTimeout(() => document.getElementById(section)?.scrollIntoView({ behavior: "smooth", block: "start" }), 0);
      } else if (routeMeetingId && !routeSection && !hashSection) setMeetingSection("overview");
      if (workspaceId && routeMeetingId && routeMeetingId !== meeting?.id) void reloadMeeting(routeMeetingId).catch((error) => setMessage(error.message));
      else if (route === "/meetings" || route === "/meetings/") setMeeting(null);
    };
    applyContext();
    window.addEventListener("evenspace:navigate", applyContext);
    return () => window.removeEventListener("evenspace:navigate", applyContext);
  }, [workspaceId, meeting?.id, reloadMeeting]);

  function navigateMeeting(meetingId: string, section: MeetingSection = "overview") {
    const sectionPath = section === "overview" ? "" : `/${section === "records" ? "agenda" : section === "checkin" ? "attendance" : section}`;
    const path = `/meetings/${meetingId}${sectionPath}`;
    window.history.pushState({}, "", path);
    window.dispatchEvent(new CustomEvent("evenspace:navigate", { detail: path }));
  }

  function openMeeting(meetingId: string) {
    setGuestJoinLink(""); setMeetingSection("overview");
    navigateMeeting(meetingId);
  }

  function changeWorkspace(id: string) {
    activeWorkspaceId.current = id;
    meetingLoadVersion.current += 1;
    setWorkspaceId(id);
    setMeetings([]); setMeeting(null); setEventDetails(null); setEventTitles({});
    setAgenda([]); setMinutes([]); setDecisions([]); setActions([]); setInvitees([]);
    setAttachments([]); setGuestRegistrations([]); setGuestJoinLink(""); setSignaturePreview(null); setMeetingSection("overview"); setMessage("");
  }

  useEffect(() => {
    void api<{ email: string }>("/auth/me").then((user) => {
      setUserEmail(user.email);
      return reloadWorkspaces();
    }).catch(() => setUserEmail(""));
  }, []);

  useEffect(() => { if (workspaceId) void reloadMeetings(workspaceId).catch((error) => setMessage(error.message)); }, [workspaceId, reloadMeetings]);

  async function authenticate(event: FormEvent) {
    event.preventDefault(); setBusy(true); setMessage("");
    try {
      if (isForgotPassword) {
        const result = await api<{ message: string }>("/auth/password-reset/request", {
          method: "POST", body: JSON.stringify({ email }),
        });
        setMessage(result.message);
      } else if (isResendVerification) {
        const result = await api<{ message: string }>("/auth/email-verification/request", {
          method: "POST", body: JSON.stringify({ email }),
        });
        setMessage(result.message);
      } else if (isRegister) {
        await api<{ user: { email: string }; workspace: Workspace }>("/auth/register", {
          method: "POST", body: JSON.stringify({ email, password, workspace_name: workspaceName }),
        });
        setIsRegister(false); setMessage("Account created. Check your email to verify it before signing in.");
      } else {
        const user = await api<{ email: string }>("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) });
        setUserEmail(user.email); await reloadWorkspaces();
      }
    } catch (error) {
      const text = error instanceof Error ? error.message : "Could not sign in";
      setNeedsVerification(text.toLowerCase().includes("verify your email"));
      setMessage(text);
    }
    finally { setBusy(false); }
  }

  async function submit(event: FormEvent, operation: () => Promise<unknown>, success: string, refresh = true) {
    event.preventDefault(); setBusy(true); setMessage("");
    try { await operation(); if (refresh && meeting) await reloadMeeting(meeting.id); setMessage(success); }
    catch (error) { setMessage(error instanceof Error ? error.message : "Request failed"); }
    finally { setBusy(false); }
  }

  async function createMeeting(event: FormEvent) {
    await submit(event, async () => {
      if (!workspaceId) throw new Error("Select a workspace before scheduling a meeting.");
      if (!meetingStart || !meetingEnd) throw new Error("Choose a start and end time.");
      const created = await api<Meeting>(`/workspaces/${workspaceId}/meetings/schedule`, {
        method: "POST", body: JSON.stringify({
          title: meetingTitle, meeting_type: meetingType,
          start_at: new Date(meetingStart).toISOString(), end_at: new Date(meetingEnd).toISOString(),
          timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "Africa/Nairobi",
          meeting_mode: meetingMode, online_url: meetingMode === "online" ? onlineUrl : null,
        }),
      });
      await reloadMeetings(); await reloadMeeting(created.id);
    }, "Meeting scheduled. Generate its QR code to invite attendees.", false);
  }

  async function generateGuestJoinLink() {
    if (!meeting || !workspaceId) return;
    setBusy(true); setMessage("");
    try {
      const result = await api<{ meeting_id: string; token: string }>(`/workspaces/${workspaceId}/meetings/${meeting.id}/join-link`, { method: "POST", body: "{}" });
      const link = `${window.location.origin}${window.location.pathname}#join-meeting/${result.meeting_id}/${result.token}`;
      setGuestJoinLink(link);
      setMessage("Guest registration QR is ready. Generating a replacement QR revokes the previous one.");
    } catch (error) { setMessage(error instanceof Error ? error.message : "Could not generate a meeting link."); }
    finally { setBusy(false); }
  }

  async function revokeGuestJoinLink() {
    if (!meeting || !workspaceId) return;
    setBusy(true);
    try {
      await api(`/workspaces/${workspaceId}/meetings/${meeting.id}/join-link`, { method: "DELETE" });
      setGuestJoinLink(""); setMessage("Guest registration QR has been revoked.");
    } catch (error) { setMessage(error instanceof Error ? error.message : "Could not revoke this meeting link."); }
    finally { setBusy(false); }
  }

  async function copyGuestJoinLink() {
    try { await navigator.clipboard.writeText(guestJoinLink); setMessage("Guest join link copied."); }
    catch { setMessage("Clipboard is unavailable. Select and copy the join link below."); }
  }

  function esc(str: string | null | undefined): string {
    if (!str) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  async function printInviteQr() {
    if (!guestJoinLink || !meeting) return;
    const win = window.open("", "_blank");
    if (!win) {
      setMessage("Pop-up window was blocked. Please allow pop-ups for this site to print the sign.");
      return;
    }
    try {
      const { BrowserQRCodeSvgWriter } = await import("@zxing/browser");
      const svgNode = new BrowserQRCodeSvgWriter().write(guestJoinLink, 280, 280);
      const svgHtml = svgNode.outerHTML;

      const title = esc(eventDetails?.title || meeting.meeting_type);
      const workspaceNameStr = esc(workspaces.find((w) => w.id === workspaceId)?.name || "EvenSpace");
      const meetingTypeStr = esc(meeting.meeting_type);
      const timeStr = eventDetails
        ? `${esc(new Date(eventDetails.start_at).toLocaleString([], { dateStyle: "full", timeStyle: "short" }))} · ${esc(eventDetails.timezone)}`
        : "";
      const agendaHtml = agenda.length > 0 ? `
        <div class="agenda-card">
          <div class="agenda-head">Planned Agenda</div>
          <ol class="agenda-ol">
            ${agenda.map((item) => `<li><strong>${esc(item.title)}</strong>${item.description ? `<span> – ${esc(item.description)}</span>` : ""}</li>`).join("")}
          </ol>
        </div>` : "";

      win.document.open();
      win.document.write(`<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Meeting QR Sign – ${title}</title>
  <style>
    @page { size: portrait; margin: 12mm; }
    * { box-sizing: border-box; }
    body {
      margin: 0; padding: 20px;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      color: #0f172a; background: #fff;
      display: flex; flex-direction: column; align-items: center; justify-content: center;
      min-height: 92vh; text-align: center;
    }
    .placard {
      width: 100%; max-width: 620px; margin: 0 auto;
      border: 3px double #0f172a; border-radius: 16px;
      padding: 2.25rem 2rem; background: #fff;
    }
    .header-bar {
      display: flex; align-items: center; justify-content: space-between;
      border-bottom: 2px solid #0f172a; padding-bottom: 0.65rem; margin-bottom: 1.25rem;
    }
    .workspace-brand {
      font-weight: 800; font-size: 0.9rem; letter-spacing: 0.1em;
      text-transform: uppercase; color: #0f172a;
    }
    .notice-badge {
      font-size: 0.72rem; font-weight: 700; letter-spacing: 0.08em;
      text-transform: uppercase; background: #0f172a; color: #fff;
      padding: 3px 10px; border-radius: 999px;
    }
    h1 {
      font-size: 1.85rem; font-weight: 800; line-height: 1.2;
      margin: 0 0 0.4rem; color: #0f172a;
    }
    .meeting-meta {
      font-size: 0.95rem; color: #475569; margin-bottom: 1.25rem; font-weight: 500;
    }
    .qr-frame {
      display: inline-block; padding: 1.25rem; background: #fff;
      border: 2px solid #0f172a; border-radius: 12px; margin: 0 auto 1.25rem;
    }
    .qr-frame svg { display: block; width: 280px; height: 280px; }
    .callout {
      font-size: 1.25rem; font-weight: 800; color: #0f172a; margin: 0 0 0.3rem;
    }
    .subtext {
      font-size: 0.9rem; color: #475569; max-width: 480px; margin: 0 auto 1.25rem; line-height: 1.45;
    }
    .steps {
      display: flex; justify-content: center; gap: 1rem; margin: 0 auto 1.25rem;
      text-align: left; max-width: 520px; font-size: 0.8rem; color: #334155;
    }
    .step-item {
      flex: 1; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 8px 10px;
    }
    .step-num {
      font-weight: 800; color: #0f172a; margin-bottom: 2px; font-size: 0.7rem;
      text-transform: uppercase; letter-spacing: 0.05em;
    }
    .agenda-card {
      margin: 1rem auto 1.25rem; padding: 0.85rem 1.15rem; background: #f8fafc;
      border: 1px dashed #cbd5e1; border-radius: 8px; text-align: left; max-width: 520px;
    }
    .agenda-head {
      font-size: 0.75rem; font-weight: 700; text-transform: uppercase;
      letter-spacing: 0.08em; color: #475569; margin-bottom: 0.4rem;
    }
    .agenda-ol { margin: 0; padding-left: 1.2rem; font-size: 0.82rem; color: #1e293b; }
    .agenda-ol li { margin-bottom: 0.2rem; }
    .url-fallback {
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      font-size: 0.72rem; color: #64748b; background: #f1f5f9; padding: 5px 10px;
      border-radius: 4px; display: inline-block; max-width: 95%; word-break: break-all;
    }
    .footer-bar {
      margin-top: 1.25rem; padding-top: 0.65rem; border-top: 1px solid #e2e8f0;
      display: flex; justify-content: space-between; font-size: 0.72rem;
      color: #94a3b8; text-transform: uppercase; letter-spacing: 0.05em;
    }
    @media print {
      body { padding: 0; }
      .placard { border: 2px solid #000; }
    }
  </style>
</head>
<body>
  <div class="placard">
    <div class="header-bar">
      <span class="workspace-brand">${workspaceNameStr}</span>
      <span class="notice-badge">Official Roll</span>
    </div>
    <h1>${title}</h1>
    <div class="meeting-meta">${meetingTypeStr}${timeStr ? ` · ${timeStr}` : ""}</div>
    <div class="qr-frame">
      ${svgHtml}
    </div>
    <div class="callout">Scan to Register Attendance</div>
    <div class="subtext">Scan this QR code with your smartphone camera to access the official attendance registration form for this meeting.</div>
    <div class="steps">
      <div class="step-item"><div class="step-num">Step 1</div>Point your camera at this QR code</div>
      <div class="step-item"><div class="step-num">Step 2</div>Tap the registration link prompt</div>
      <div class="step-item"><div class="step-num">Step 3</div>Submit your name to sign the roll</div>
    </div>
    ${agendaHtml}
    <div><span class="url-fallback">${esc(guestJoinLink)}</span></div>
    <div class="footer-bar">
      <span>EvenSpace Governance</span>
      <span>Institutional Meeting Record</span>
    </div>
  </div>
</body>
</html>`);
      win.document.close();
      setTimeout(() => {
        win.focus();
        win.print();
      }, 250);
    } catch {
      win.close();
      setMessage("Could not generate the printable meeting QR sign.");
    }
  }

  async function downloadQrSvg() {
    if (!guestJoinLink || !meeting) return;
    try {
      const { BrowserQRCodeSvgWriter } = await import("@zxing/browser");
      const svgNode = new BrowserQRCodeSvgWriter().write(guestJoinLink, 360, 360);
      const svgBlob = new Blob([svgNode.outerHTML], { type: "image/svg+xml;charset=utf-8" });
      const url = URL.createObjectURL(svgBlob);
      const anchor = document.createElement("a");
      anchor.href = url;
      const slug = (eventDetails?.title || meeting.meeting_type).toLowerCase().replace(/[^a-z0-9]+/g, "-");
      anchor.download = `meeting-qr-${slug}.svg`;
      anchor.click();
      URL.revokeObjectURL(url);
      setMessage("Meeting QR code SVG downloaded.");
    } catch {
      setMessage("Could not download the QR SVG.");
    }
  }

  function csvCell(value: string | null | undefined): string {
    const text = value ?? "";
    if (/[",\r\n]/.test(text)) {
      return `"${text.replace(/"/g, '""')}"`;
    }
    return text;
  }

  function exportAttendeesCsv() {
    if (!meeting) return;
    const lines = [
      ["Full Name", "Email", "Phone", "Attendee Type", "Organization / Department", "Attendance Status", "Registered At", "Notes"],
      ...guestRegistrations.map((row) => [
        row.full_name,
        row.email,
        row.phone,
        attendeeRoleLabel(row.attendee_type),
        row.organization || "",
        row.attendance_status,
        new Date(row.registered_at).toLocaleString(),
        row.attendance_note || "",
      ]),
    ].map((line) => line.map(csvCell).join(",")).join("\r\n");

    const blob = new Blob([`\uFEFF${lines}`], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    const slug = (eventDetails?.title || meeting.meeting_type).toLowerCase().replace(/[^a-z0-9]+/g, "-");
    anchor.download = `meeting-attendance-${slug}.csv`;
    anchor.click();
    URL.revokeObjectURL(url);
    setMessage("Attendee attendance roll exported as CSV (Excel compatible).");
  }

  function printAttendancePdf() {
    if (!meeting) return;
    const win = window.open("", "_blank");
    if (!win) {
      setMessage("Pop-up window was blocked. Please allow pop-ups to print the attendance roll.");
      return;
    }
    const title = esc(eventDetails?.title || meeting.meeting_type);
    const workspaceNameStr = esc(workspaces.find((w) => w.id === workspaceId)?.name || "EvenSpace");
    const timeStr = eventDetails
      ? `${esc(new Date(eventDetails.start_at).toLocaleString([], { dateStyle: "full", timeStyle: "short" }))} · ${esc(eventDetails.timezone)}`
      : "";
    const presentCount = guestRegistrations.filter((r) => r.attendance_status === "present").length;
    const absentCount = guestRegistrations.filter((r) => r.attendance_status === "absent").length;
    const excusedCount = guestRegistrations.filter((r) => r.attendance_status === "excused").length;

    win.document.open();
    win.document.write(`<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Attendance Register – ${title}</title>
  <style>
    @page { size: A4 landscape; margin: 12mm; }
    * { box-sizing: border-box; }
    body {
      margin: 0; padding: 16px;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      color: #0f172a; background: #fff;
    }
    .register-header {
      border-bottom: 2px solid #0f172a; padding-bottom: 12px; margin-bottom: 16px;
      display: flex; justify-content: space-between; align-items: flex-end;
    }
    .register-title h1 { margin: 0 0 4px; font-size: 1.5rem; color: #0f172a; }
    .register-title p { margin: 0; color: #475569; font-size: 0.9rem; }
    .badge {
      display: inline-block; padding: 4px 10px; border-radius: 999px;
      background: #0f172a; color: #fff; font-size: 0.75rem; font-weight: 700;
      text-transform: uppercase; letter-spacing: 0.08em;
    }
    .stats-row {
      display: flex; gap: 12px; margin-bottom: 16px;
    }
    .stat-pill {
      background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px;
      padding: 6px 14px; font-size: 0.85rem; color: #334155; font-weight: 600;
    }
    .stat-pill strong { color: #0f172a; font-size: 1rem; margin-right: 4px; }
    table {
      width: 100%; border-collapse: collapse; margin-bottom: 24px; font-size: 0.85rem;
    }
    th, td {
      border: 1px solid #cbd5e1; padding: 8px 10px; text-align: left;
    }
    th {
      background: #f1f5f9; font-weight: 700; color: #1e293b; text-transform: uppercase;
      font-size: 0.75rem; letter-spacing: 0.05em;
    }
    tr:nth-child(even) td { background: #fafafa; }
    .status-tag {
      display: inline-block; padding: 2px 8px; border-radius: 4px;
      font-size: 0.75rem; font-weight: 700; text-transform: uppercase;
    }
    .status-present { background: #dcfce7; color: #166534; }
    .status-absent { background: #fee2e2; color: #991b1b; }
    .status-excused { background: #fef3c7; color: #92400e; }
    .status-registered { background: #e2e8f0; color: #334155; }
    .sign-section {
      margin-top: 32px; display: grid; grid-template-columns: 1fr 1fr; gap: 40px;
      font-size: 0.85rem; color: #334155; page-break-inside: avoid;
    }
    .sign-box { border-top: 1px solid #94a3b8; padding-top: 8px; }
    .footer-note {
      margin-top: 24px; font-size: 0.75rem; color: #94a3b8; text-align: right;
    }
  </style>
</head>
<body>
  <div class="register-header">
    <div class="register-title">
      <div style="font-size:0.8rem;text-transform:uppercase;letter-spacing:0.1em;color:#64748b;font-weight:700;">${workspaceNameStr} · Meeting Attendance Register</div>
      <h1>${title}</h1>
      <p>${timeStr ? `${timeStr} · ` : ""}${esc(meeting.meeting_type)} (${esc(meeting.status)})</p>
    </div>
    <div><span class="badge">Official Record</span></div>
  </div>

  <div class="stats-row">
    <div class="stat-pill"><strong>${guestRegistrations.length}</strong> Total Registered</div>
    <div class="stat-pill"><strong>${presentCount}</strong> Present</div>
    <div class="stat-pill"><strong>${absentCount}</strong> Absent</div>
    <div class="stat-pill"><strong>${excusedCount}</strong> Excused</div>
  </div>

  <table>
    <thead>
      <tr>
        <th style="width:36px">#</th>
        <th>Full Name</th>
        <th>Type</th>
        <th>Email & Phone</th>
        <th>Department / Organization</th>
        <th>Attendance Status</th>
        <th style="width:140px">Signature / Verification</th>
      </tr>
    </thead>
    <tbody>
      ${guestRegistrations.map((r, i) => `
        <tr>
          <td>${i + 1}</td>
          <td><strong>${esc(r.full_name)}</strong></td>
          <td>${esc(attendeeRoleLabel(r.attendee_type))}</td>
          <td>${esc(r.email)}<br /><small style="color:#64748b">${esc(r.phone)}</small></td>
          <td>${esc(r.organization || "—")}</td>
          <td><span class="status-tag status-${esc(r.attendance_status)}">${esc(r.attendance_status)}</span></td>
          <td></td>
        </tr>
      `).join("")}
      ${!guestRegistrations.length ? `<tr><td colspan="7" style="text-align:center;color:#64748b;padding:20px;">No attendees registered yet.</td></tr>` : ""}
    </tbody>
  </table>

  <div class="sign-section">
    <div class="sign-box">
      <strong>Meeting Secretary / Recorder:</strong><br /><br />
      Name: ____________________________________ Signature: ______________________ Date: ___________
    </div>
    <div class="sign-box">
      <strong>Chairperson / Presiding Officer:</strong><br /><br />
      Name: ____________________________________ Signature: ______________________ Date: ___________
    </div>
  </div>

  <div class="footer-note">Generated by EvenSpace Governance Platform · ${new Date().toLocaleString()}</div>
</body>
</html>`);
    win.document.close();
    setTimeout(() => {
      win.focus();
      win.print();
    }, 250);
  }

  function printMeetingReport() {
    if (!meeting) return;
    const win = window.open("", "_blank");
    if (!win) {
      setMessage("Pop-up window was blocked. Please allow pop-ups to print the meeting dossier.");
      return;
    }
    const title = esc(eventDetails?.title || meeting.meeting_type);
    const workspaceNameStr = esc(workspaces.find((w) => w.id === workspaceId)?.name || "EvenSpace");
    const timeStr = eventDetails
      ? `${esc(new Date(eventDetails.start_at).toLocaleString([], { dateStyle: "full", timeStyle: "short" }))} · ${esc(eventDetails.timezone)}`
      : "";
    const approvedMinutes = minutes.filter((m) => m.status === "approved" || m.status === "submitted");

    win.document.open();
    win.document.write(`<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Meeting Dossier – ${title}</title>
  <style>
    @page { size: A4 portrait; margin: 15mm; }
    * { box-sizing: border-box; }
    body {
      margin: 0; padding: 16px;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      color: #0f172a; background: #fff; line-height: 1.5;
    }
    .header {
      border-bottom: 3px double #0f172a; padding-bottom: 14px; margin-bottom: 20px;
    }
    .header .org { font-size: 0.85rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.1em; color: #64748b; }
    .header h1 { margin: 6px 0 4px; font-size: 1.7rem; color: #0f172a; }
    .header .meta { font-size: 0.95rem; color: #334155; }
    .section { margin-bottom: 24px; page-break-inside: avoid; }
    .section-title {
      font-size: 1.1rem; font-weight: 800; color: #0f172a; border-bottom: 1px solid #cbd5e1;
      padding-bottom: 4px; margin-bottom: 10px; text-transform: uppercase; letter-spacing: 0.05em;
    }
    ol, ul { margin: 0 0 10px; padding-left: 20px; font-size: 0.9rem; }
    li { margin-bottom: 6px; }
    .minutes-content {
      background: #f8fafc; border-left: 3px solid #0f172a; padding: 12px 16px;
      white-space: pre-wrap; font-family: inherit; font-size: 0.9rem; margin-bottom: 12px;
    }
    table { width: 100%; border-collapse: collapse; font-size: 0.85rem; margin-top: 8px; }
    th, td { border: 1px solid #cbd5e1; padding: 6px 8px; text-align: left; }
    th { background: #f1f5f9; font-weight: 700; font-size: 0.75rem; text-transform: uppercase; }
    .footer {
      margin-top: 30px; padding-top: 10px; border-top: 1px solid #e2e8f0;
      font-size: 0.75rem; color: #94a3b8; display: flex; justify-content: space-between;
    }
  </style>
</head>
<body>
  <div class="header">
    <div class="org">${workspaceNameStr} · Institutional Governance</div>
    <h1>${title}</h1>
    <div class="meta">${esc(meeting.meeting_type)} · ${timeStr ? `${timeStr} · ` : ""}Status: <strong>${esc(meeting.status)}</strong></div>
  </div>

  <div class="section">
    <div class="section-title">1. Agenda</div>
    ${agenda.length > 0 ? `
      <ol>
        ${agenda.map((a) => `<li><strong>${esc(a.title)}</strong>${a.description ? ` — ${esc(a.description)}` : ""}</li>`).join("")}
      </ol>` : `<p style="font-size:0.9rem;color:#64748b;">No formal agenda items recorded.</p>`}
  </div>

  <div class="section">
    <div class="section-title">2. Minutes of the Meeting</div>
    ${approvedMinutes.length > 0 ? approvedMinutes.map((m) => `
      <div style="font-size:0.8rem;color:#64748b;margin-bottom:4px;"><strong>Revision ${m.revision} (${m.status})</strong></div>
      <div class="minutes-content">${esc(m.content)}</div>
    `).join("") : `<p style="font-size:0.9rem;color:#64748b;">No submitted or approved minutes yet.</p>`}
  </div>

  <div class="section">
    <div class="section-title">3. Decisions & Resolutions</div>
    ${decisions.length > 0 ? `
      <ol>
        ${decisions.map((d) => `<li><strong>Resolution #${d.decision_number}: ${esc(d.title)}</strong> (${esc(d.status)})<br /><span style="color:#475569;">${esc(d.details)}</span></li>`).join("")}
      </ol>` : `<p style="font-size:0.9rem;color:#64748b;">No formal decisions recorded.</p>`}
  </div>

  <div class="section">
    <div class="section-title">4. Action Items & Follow-up</div>
    ${actions.length > 0 ? `
      <table>
        <thead>
          <tr><th>Action Item</th><th>Status</th><th>Due Date</th></tr>
        </thead>
        <tbody>
          ${actions.map((act) => `<tr><td><strong>${esc(act.title)}</strong>${act.details ? `<br /><small>${esc(act.details)}</small>` : ""}</td><td style="text-transform:capitalize">${esc(act.status.replace("_", " "))}</td><td>${act.due_at ? esc(new Date(act.due_at).toLocaleDateString()) : "—"}</td></tr>`).join("")}
        </tbody>
      </table>` : `<p style="font-size:0.9rem;color:#64748b;">No follow-up action items assigned.</p>`}
  </div>

  <div class="section">
    <div class="section-title">5. Attendance Roll (${guestRegistrations.length + invitees.length} Attendees)</div>
    ${guestRegistrations.length > 0 ? `
      <table>
        <thead>
          <tr><th>#</th><th>Name</th><th>Role</th><th>Organization</th><th>Status</th></tr>
        </thead>
        <tbody>
          ${guestRegistrations.map((r, i) => `<tr><td>${i + 1}</td><td><strong>${esc(r.full_name)}</strong></td><td>${esc(r.attendee_type)}</td><td>${esc(r.organization || "—")}</td><td>${esc(r.attendance_status)}</td></tr>`).join("")}
        </tbody>
      </table>` : `<p style="font-size:0.9rem;color:#64748b;">No attendees on the roll.</p>`}
  </div>

  <div class="footer">
    <span>EvenSpace Institutional Record</span>
    <span>Generated: ${new Date().toLocaleString()}</span>
  </div>
</body>
</html>`);
    win.document.close();
    setTimeout(() => {
      win.focus();
      win.print();
    }, 250);
  }

  if (!userEmail) return <main className="meeting-shell">
    <header className="meeting-header"><a className="brand" href="#top"><span className="brand-mark"><span /></span><span>evenspace</span></a><div className="meeting-user"><button className="meeting-link" onClick={onGate}>Gate scanner</button><span className="meeting-tag">MEETING GOVERNANCE</span></div></header>
    <section className="meeting-welcome"><span className="meeting-kicker"><CalendarDays size={15} /> WORKSPACE MEETINGS</span><h1>Meet with <em>purpose.</em></h1><p>Prepare agendas, approve minutes, record decisions, and follow actions through.</p></section>
    <form className="meeting-card auth-card" onSubmit={(event) => void authenticate(event)}>
      <h2>{isForgotPassword ? "Reset your password" : isResendVerification ? "Verify your email" : isRegister ? "Create your workspace" : "Sign in to EvenSpace"}</h2>
      <label className="field"><span>Email</span><input type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} /></label>
      {!isForgotPassword && !isResendVerification && <label className="field"><span>Password</span><input type="password" required minLength={isRegister ? 12 : 1} autoComplete={isRegister ? "new-password" : "current-password"} value={password} onChange={(e) => setPassword(e.target.value)} /></label>}
      {isRegister && !isForgotPassword && !isResendVerification && <label className="field"><span>Workspace name</span><input required value={workspaceName} onChange={(e) => setWorkspaceName(e.target.value)} /></label>}
      {message && <p className="meeting-message" role={isForgotPassword || isResendVerification || message.startsWith("Account created") ? "status" : "alert"}>{message}</p>}
      <button className="button button-primary full-width" disabled={busy}><LogIn size={16} /> {busy ? "Please wait…" : isForgotPassword ? "Send reset link" : isResendVerification ? "Send verification link" : isRegister ? "Create account" : "Sign in"}</button>
      {isForgotPassword || isResendVerification ? <button className="meeting-link" type="button" onClick={() => { setIsForgotPassword(false); setIsResendVerification(false); setMessage(""); }}>Back to sign in</button> : <>
        {!isRegister && <button className="meeting-link" type="button" onClick={() => { setIsForgotPassword(true); setIsResendVerification(false); setMessage(""); }}>Forgot password?</button>}
        {(needsVerification || message.startsWith("Account created")) && <button className="meeting-link" type="button" onClick={() => { setIsResendVerification(true); setIsForgotPassword(false); setMessage(""); }}>Resend verification email</button>}
        <button className="meeting-link" type="button" onClick={() => { setIsRegister(!isRegister); setNeedsVerification(false); setMessage(""); }}>{isRegister ? "Already have an account? Sign in" : "New to EvenSpace? Create an account"}</button>
      </>}
    </form>
    <footer className="footer"><span>EVENSPACE</span><span>Institutional meeting records</span></footer>
  </main>;

  if (showOrganizer) return <OrganizerDashboard onMeetings={() => setShowOrganizer(false)} onGate={onGate} onParticipant={onParticipant} />;

  const base = meeting && workspaceId ? `/workspaces/${workspaceId}/meetings/${meeting.id}` : "";
  return <main className="meeting-shell">
    <header className="meeting-header">
      <a className="brand" href="#top"><span className="brand-mark"><span /></span><span>evenspace</span></a>
      <div className="meeting-user">
        <button className="meeting-link" type="button" onClick={() => onEvents ? onEvents() : setShowOrganizer(true)}>Events</button>
        <span className="current-nav-pill">Meetings</span>
        <button className="meeting-link" type="button" onClick={onGate}>Gate scanner</button>
        {onParticipant && <button className="meeting-link" type="button" onClick={onParticipant}>My tickets</button>}
        <span>{userEmail}</span>
        <button type="button" className="meeting-link" onClick={() => void api("/auth/logout", { method: "POST" }).then(() => { setUserEmail(""); setMeeting(null); }).catch((e) => setMessage(e.message))}>Sign out</button>
      </div>
    </header>
    <section className="meeting-welcome"><span className="meeting-kicker"><CalendarDays size={15} /> MEETING GOVERNANCE</span><h1>Run the meeting, <em>keep the record.</em></h1><p>Manage agendas, approvals, decisions, attendance, and accountable follow-through.</p></section>
    {message && <div className="notice notice-info" role="status">{message}<button className="meeting-dismiss" onClick={() => setMessage("")}>×</button></div>}
    <section className="meeting-card workspace-bar"><label className="field"><span>Workspace</span><select value={workspaceId} onChange={(e) => changeWorkspace(e.target.value)}>
      {workspaces.map((row) => <option key={row.id} value={row.id}>{row.name} · {row.role}</option>)}</select></label><button className="button button-secondary" onClick={() => void reloadMeetings()}><RefreshCw size={15} /> Refresh</button></section>
    <nav className="meeting-tabs" role="group" aria-label="Meeting workspace sections">
      {(["overview", "attendees", "records", "invitations", "checkin"] as MeetingSection[]).map((section) => <button key={section} type="button" aria-pressed={meetingSection === section} className={meetingSection === section ? "active" : ""} onClick={() => { setMeetingSection(section); if (meeting) navigateMeeting(meeting.id, section); }}>
        {section === "records" ? "Agenda & records" : section === "checkin" ? "Check-in" : section[0].toUpperCase() + section.slice(1)}
      </button>)}
    </nav>
    {meetingSection === "invitations" && <div className="meeting-settings-panels" id="invitations">
      {meeting && <section className="meeting-card">
        <div className="meeting-section-title"><div><h2>Meeting invitees</h2><p>Add workspace members to this meeting’s attendee list.</p></div></div>
        <form className="meeting-inline-form" onSubmit={(event) => void submit(event, () => api(`${base}/invitees`, { method: "POST", body: JSON.stringify({ user_id: new FormData(event.currentTarget).get("user_id") }) }), "Meeting invitee added.")}>
          <input name="user_id" required placeholder="Workspace member account ID" /><button className="button button-primary" disabled={busy}>Add invitee</button>
        </form>
        <p className="meeting-empty">Review invitee status and record attendance in the Attendees section.</p>
      </section>}
      <WorkspaceInvitations workspaceId={workspaceId} role={workspaces.find((row) => row.id === workspaceId)?.role ?? ""} />
      {["owner", "admin"].includes(workspaces.find((row) => row.id === workspaceId)?.role ?? "") && (
      <section className="meeting-card">
        <div className="meeting-section-title">
          <div><h2><Mail size={16} style={{ display: "inline", verticalAlign: "middle" }} /> Email Templates</h2><p>Customize automated notification emails for this workspace</p></div>
          <button className="button button-secondary" type="button" onClick={() => setShowEmailTemplates((v) => !v)}>
            {showEmailTemplates ? "Hide templates" : "Manage templates"}
          </button>
        </div>
        {showEmailTemplates && <NotificationTemplates workspaceId={workspaceId} canManage={true} />}
      </section>
      )}
    </div>}
    <div className="meeting-layout">
      <aside className="meeting-card meeting-sidebar" id="meeting-list"><div className="meeting-section-title"><div><h2>Meetings</h2><p>Private workspace events</p></div></div>
        <form className="meeting-create" onSubmit={(e) => void createMeeting(e)}>
          <label className="field"><span>Meeting title</span><input required maxLength={200} value={meetingTitle} onChange={(e) => setMeetingTitle(e.target.value)} placeholder="Quarterly staff conference" /></label>
          <label className="field"><span>Meeting type</span><input required maxLength={80} value={meetingType} onChange={(e) => setMeetingType(e.target.value)} /></label>
          <label className="field"><span>Starts</span><input required type="datetime-local" value={meetingStart} onChange={(e) => setMeetingStart(e.target.value)} /></label>
          <label className="field"><span>Ends</span><input required type="datetime-local" value={meetingEnd} onChange={(e) => setMeetingEnd(e.target.value)} /></label>
          <label className="field"><span>Meeting format</span><select value={meetingMode} onChange={(e) => setMeetingMode(e.target.value as "physical" | "online")}><option value="physical">Physical</option><option value="online">Online</option></select></label>
          {meetingMode === "online" && <label className="field"><span>Google Meet or Zoom link</span><input required type="url" value={onlineUrl} onChange={(e) => setOnlineUrl(e.target.value)} placeholder="https://meet.google.com/..." /></label>}
          <small className="meeting-timezone-note">Times use {Intl.DateTimeFormat().resolvedOptions().timeZone || "your device timezone"}.</small>
          <button className="button button-primary full-width" disabled={busy || !workspaceId}><Plus size={15} /> Schedule meeting</button>
        </form>
        <label className="field meeting-search"><span>Search meetings</span><input type="search" value={meetingSearch} onChange={(event) => setMeetingSearch(event.target.value)} placeholder="Search by title or type" /></label>
        <div className="meeting-list">{meetings.filter((row) => `${eventTitles[row.event_id] ?? ""} ${row.meeting_type} ${row.status}`.toLocaleLowerCase().includes(meetingSearch.trim().toLocaleLowerCase())).map((row) => <button key={row.id} className={`meeting-list-item ${meeting?.id === row.id ? "selected" : ""}`} onClick={() => openMeeting(row.id)}>
      <strong>{eventTitles[row.event_id] || row.meeting_type}</strong><span>{row.meeting_type} · {row.status}</span>
        </button>)}{!meetings.length && <p className="meeting-empty">No meeting records yet.</p>}{meetings.length > 0 && !meetings.some((row) => `${eventTitles[row.event_id] ?? ""} ${row.meeting_type} ${row.status}`.toLocaleLowerCase().includes(meetingSearch.trim().toLocaleLowerCase())) && <p className="meeting-empty">No meetings match your search.</p>}</div>
      </aside>
      {meeting ? <div className="meeting-content">
        {meetingSection === "overview" && <section className="meeting-card meeting-summary"><div><span className="meeting-kicker">{meeting.status.toUpperCase()} · {meeting.meeting_type}</span><h2>{eventDetails?.title || meeting.meeting_type}</h2><p>{eventDetails ? `${new Date(eventDetails.start_at).toLocaleString()} · ${eventDetails.timezone}` : `Event ID · ${meeting.event_id}`}</p><p>{meeting.meeting_mode === "online" ? "Online meeting" : "Physical meeting"}</p></div>
          <div className="record-actions">
            <button className="button button-secondary" type="button" onClick={() => void printMeetingReport()} title="Print complete meeting package (agenda, minutes, decisions, actions, attendance)"><FileText size={14} /> Full Dossier / PDF</button>
            {meeting.status === "scheduled" && meeting.meeting_mode === "online" && meeting.online_url && <a className="button button-secondary" href={meeting.online_url} target="_blank" rel="noreferrer">Join online</a>}
            {meeting.status === "draft" && <button className="button button-primary" disabled={busy} onClick={() => void submit(new Event("submit") as unknown as FormEvent, () => api(`${base}/status`, { method: "POST", body: JSON.stringify({ status: "scheduled" }) }), "Meeting scheduled.")}>Schedule</button>}
            {meeting.status === "scheduled" && <button className="button button-primary" disabled={busy} onClick={() => void submit(new Event("submit") as unknown as FormEvent, () => api(`${base}/status`, { method: "POST", body: JSON.stringify({ status: "held" }) }), "Meeting marked held.")}>Mark held</button>}
            {meeting.status === "scheduled" && <button className="button button-secondary" disabled={busy} onClick={() => { const note = window.prompt("Reason for cancellation"); if (note?.trim()) void submit(new Event("submit") as unknown as FormEvent, () => api(`${base}/status`, { method: "POST", body: JSON.stringify({ status: "cancelled", note }) }), "Meeting cancelled."); }}>Cancel</button>}
          </div>
        </section>}
        {meetingSection === "checkin" && meeting.status === "scheduled" && <section className="meeting-card guest-qr-card">
          <div className="meeting-section-title"><div><h2>Guest registration QR</h2><p>Attendees scan this code to join the meeting list.</p></div><span className="meeting-kicker"><QrCode size={14} /> PRIVATE LINK</span></div>
          {!guestJoinLink ? <div className="guest-qr-empty"><p>Generate a QR after scheduling, then display it at the entrance or share its link with attendees. Attendee phones must be able to reach the address used to open EvenSpace.</p><button className="button button-primary" disabled={busy} onClick={() => void generateGuestJoinLink()}><QrCode size={15} /> Generate meeting QR</button></div> : <div className="guest-qr-content">
            <MeetingQrCode value={guestJoinLink} />
            <div className="guest-qr-details"><strong>{eventDetails?.title || meeting.meeting_type} registration</strong><span>Staff and guests register with their contact details and a signature. Location sharing is optional.</span><label className="field"><span>Join link</span><input readOnly value={guestJoinLink} onFocus={(event) => event.currentTarget.select()} /></label>
              <div className="record-actions">
                <button className="button button-primary" type="button" onClick={() => void printInviteQr()}><Printer size={14} /> Print QR sign</button>
                <button className="button button-secondary" type="button" onClick={() => void downloadQrSvg()}><Download size={14} /> Download SVG</button>
                <button className="button button-secondary" onClick={() => void copyGuestJoinLink()}><Clipboard size={14} /> Copy link</button>
                <button className="button button-secondary" disabled={busy} onClick={() => void generateGuestJoinLink()}><Link2 size={14} /> Replace QR</button>
                <button className="meeting-remove" disabled={busy} onClick={() => void revokeGuestJoinLink()}>Revoke</button>
              </div>
              <small>Replacing or revoking the QR immediately invalidates the previous link. Keep the generated code with the meeting materials. For attendees’ phones, use a network-reachable HTTPS address rather than localhost.</small>
            </div>
          </div>}
        </section>}
        {meetingSection === "checkin" && meeting.status !== "scheduled" && <section className="meeting-card" id="checkin">
          <div className="meeting-section-title"><div><h2>Meeting check-in</h2><p>QR registration links close when a meeting is held or cancelled.</p></div></div>
          <p className="meeting-empty">This meeting is {meeting.status}. Review its saved attendee registrations and record attendance in the Attendees section.</p>
          <button className="button button-secondary" type="button" onClick={() => setMeetingSection("attendees")}>Review attendees</button>
        </section>}
        {meetingSection === "records" && <>
        <section className="meeting-card" id="records"><div className="meeting-section-title"><div><h2>Agenda</h2><p>Ordered discussion items</p></div></div>
          <form className="meeting-inline-form" onSubmit={(event) => void submit(event, () => api(`${base}/agenda`, { method: "POST", body: JSON.stringify({ title: new FormData(event.currentTarget).get("title"), description: new FormData(event.currentTarget).get("description") || null }) }), "Agenda item added.")}>
            <input name="title" required placeholder="Agenda item" /><input name="description" placeholder="Purpose or notes" /><button className="button button-primary" disabled={busy}>Add</button>
          </form>
          <ol className="meeting-ordered-list">{agenda.map((item) => <li key={item.id}><span><strong>{item.title}</strong>{item.description && <small>{item.description}</small>}</span>{meeting.status !== "held" && meeting.status !== "cancelled" && <button className="meeting-remove" onClick={() => void submit(new Event("submit") as unknown as FormEvent, () => api(`${base}/agenda/${item.id}`, { method: "DELETE" }), "Agenda item removed.")}>Remove</button>}</li>)}{!agenda.length && <p className="meeting-empty">Agenda items will appear here.</p>}</ol>
        </section>
        <section className="meeting-card"><div className="meeting-section-title"><div><h2>Attachments</h2><p>Private files stored with this meeting (10 MB maximum each)</p></div></div>
          <form className="meeting-inline-form attachment-form" onSubmit={(event) => void submit(event, () => {
            const form = new FormData(event.currentTarget);
            const file = form.get("file");
            if (!(file instanceof File) || !file.size) throw new Error("Choose a file to upload");
            const upload = new FormData(); upload.append("file", file);
            return api(`${base}/attachments`, { method: "POST", body: upload });
          }, "Attachment uploaded.")}><input name="file" type="file" required accept=".pdf,.png,.jpg,.jpeg,.txt,.docx,.xlsx,.pptx" /><button className="button button-primary" disabled={busy}>Upload file</button></form>
          <div className="meeting-record-list">{attachments.map((file) => <div className="meeting-record" key={file.id}><div><strong>{file.filename}</strong><small>{(file.size_bytes / 1024).toFixed(1)} KB · {file.media_type}</small></div><div className="record-actions"><a className="button button-secondary" href={`${API_BASE}/workspaces/${workspaceId}/meetings/${meeting.id}/attachments/${file.id}/download`} target="_blank" rel="noreferrer">Download</a><button className="meeting-remove" onClick={() => void submit(new Event("submit") as unknown as FormEvent, () => api(`${base}/attachments/${file.id}`, { method: "DELETE" }), "Attachment deleted.")}>Delete</button></div></div>)}{!attachments.length && <p className="meeting-empty">No meeting files uploaded.</p>}</div>
        </section>
        </>}
        {meetingSection === "attendees" && <section className="meeting-card" id="attendees"><div className="meeting-section-title"><div><h2>Attendees & attendance</h2><p><Users size={13} /> Member invitees and registered attendees</p></div></div>
          {meeting.status === "scheduled" && <div className="manual-attendee-panel">
            <h3>Add attendee directly</h3><p>Use this if someone cannot register through the meeting link. No signature or GPS is collected in this organizer flow.</p>
            <form className="manual-attendee-form" onSubmit={(event) => void submit(event, () => {
              const values = new FormData(event.currentTarget);
              return api(`${base}/guest-registrations`, { method: "POST", body: JSON.stringify({
                full_name: values.get("full_name"), email: values.get("email"), phone: values.get("phone"),
                attendee_type: values.get("attendee_type"), organization: values.get("organization") || null,
              }) });
            }, "Attendee added to the meeting.")}>
              <label className="field"><span>Full name</span><input name="full_name" required maxLength={200} autoComplete="name" /></label>
              <label className="field"><span>Email address</span><input name="email" required type="email" autoComplete="email" /></label>
              <label className="field"><span>Phone number</span><input name="phone" required type="tel" minLength={7} maxLength={24} autoComplete="tel" /></label>
              <label className="field"><span>Attendee role</span><select name="attendee_type" defaultValue="member_delegate"><option value="speaker">Speaker</option><option value="secretary">Secretary</option><option value="chairperson">Chairperson</option><option value="member_delegate">Member / Delegate</option></select></label>
              <label className="field"><span>Department or organization (optional)</span><input name="organization" maxLength={200} /></label>
              <button className="button button-primary" disabled={busy}>Add attendee</button>
            </form>
          </div>}
          <div className="meeting-record-list">{invitees.map((person) => <div className="meeting-record" key={person.id}><div><strong>{person.user_id}</strong><small>Attendance · {person.attendance_status}{person.attendance_note ? ` · ${person.attendance_note}` : ""}</small></div>{meeting.status === "held" && <select aria-label="Attendance" value={person.attendance_status === "pending" ? "present" : person.attendance_status} onChange={(e) => void submit(new Event("submit") as unknown as FormEvent, () => api(`${base}/invitees/${person.id}/attendance`, { method: "POST", body: JSON.stringify({ status: e.target.value }) }), "Attendance saved.")}><option value="present">Present</option><option value="absent">Absent</option><option value="excused">Excused</option></select>}</div>)}{!invitees.length && !guestRegistrations.length && <p className="meeting-empty">No one has joined this meeting yet.</p>}</div>
          <div className="guest-attendees">
            <div className="guest-attendees-heading">
              <h3>Attendee registrations ({guestRegistrations.length})</h3>
              <div className="record-actions">
                {guestRegistrations.length > 0 && (
                  <>
                    <button className="button button-secondary" type="button" onClick={() => void exportAttendeesCsv()}>
                      <Download size={13} /> Export CSV
                    </button>
                    <button className="button button-secondary" type="button" onClick={() => void printAttendancePdf()}>
                      <Printer size={13} /> Print Roll / PDF
                    </button>
                  </>
                )}
                <button className="meeting-link" type="button" onClick={() => void reloadMeeting(meeting.id).catch((error) => setMessage(error.message))}>
                  Refresh list
                </button>
              </div>
            </div>
            {guestRegistrations.map((person) => <div className="meeting-record guest-attendee" key={person.id}><div><strong>{person.full_name} <span className="attendee-type-tag">{attendeeRoleLabel(person.attendee_type)}</span></strong><small>{person.email} · {person.phone}{person.organization ? ` · ${person.organization}` : ""}</small><small>Registered {new Date(person.registered_at).toLocaleString()} · {person.attendance_status}{person.registration_source === "admin" ? " · Added by organizer" : ""}</small>
              {person.registration_source === "admin" && <small className="manual-attendee-note">Signature and GPS were not collected for this organizer-added attendee.</small>}
              {person.gps_latitude !== null && person.gps_longitude !== null && <small className="guest-location"><MapPin size={12} /> {person.gps_latitude.toFixed(5)}, {person.gps_longitude.toFixed(5)}{person.gps_accuracy_m !== null ? ` · ±${Math.round(person.gps_accuracy_m)} m` : ""}{person.gps_captured_at ? ` · ${new Date(person.gps_captured_at).toLocaleString()}` : ""}</small>}
              {person.signature_present && <div className="guest-signature-access"><button className="meeting-link" type="button" onClick={() => void toggleSignaturePreview(person.id)}>{signaturePreview?.attendeeId === person.id ? "Hide signature" : "View signature"}</button>{signaturePreview?.attendeeId === person.id && <img src={signaturePreview.url} alt={`Digital signature provided by ${person.full_name}`} />}</div>}
              {(person.signature_present || person.gps_latitude !== null) && <button className="meeting-remove" type="button" disabled={busy} onClick={() => eraseAttendeePrivacyData(person.id)}>Delete signature & location data</button>}
            </div><div className="record-actions">{meeting.status === "scheduled" && meeting.meeting_mode === "online" && meeting.online_url && <a className="button button-secondary" href={meeting.online_url} target="_blank" rel="noreferrer">Join online</a>}{meeting.status === "held" && <select aria-label={`Attendance for ${person.full_name}`} value={person.attendance_status === "registered" ? "present" : person.attendance_status} onChange={(e) => void submit(new Event("submit") as unknown as FormEvent, () => api(`${base}/guest-registrations/${person.id}/attendance`, { method: "POST", body: JSON.stringify({ status: e.target.value }) }), "Guest attendance saved.")}><option value="present">Present</option><option value="absent">Absent</option><option value="excused">Excused</option></select>}</div></div>)}
            {!guestRegistrations.length && <p className="meeting-empty">Guest registrations from the QR form will appear here.</p>}
          </div>
        </section>}
        {meetingSection === "records" && <>
        <section className="meeting-card"><div className="meeting-section-title"><div><h2>Minutes</h2><p>Submitted and approved versions are retained as revisions</p></div></div>
          <form className="meeting-stack-form" onSubmit={(event) => void submit(event, () => api(`${base}/minutes`, { method: "POST", body: JSON.stringify({ content: new FormData(event.currentTarget).get("content") }) }), "Minutes revision saved.")}><textarea name="content" required rows={4} placeholder="Write the meeting minutes…" /><button className="button button-primary" disabled={busy}>Save new revision</button></form>
          <div className="meeting-record-list">{minutes.map((row) => <article className="meeting-record" key={row.id}><div><strong>Revision {row.revision} · {row.status}</strong><small>{row.content}</small></div><div className="record-actions">{row.status === "draft" && <button className="button button-secondary" onClick={() => void submit(new Event("submit") as unknown as FormEvent, () => api(`${base}/minutes/${row.id}/submit`, { method: "POST" }), "Minutes submitted.")}>Submit</button>}{row.status === "submitted" && <button className="button button-primary" onClick={() => void submit(new Event("submit") as unknown as FormEvent, () => api(`${base}/minutes/${row.id}/approve`, { method: "POST", body: JSON.stringify({ note: null }) }), "Minutes approved.")}>Approve</button>}{row.status === "approved" && (
            <button className="button button-secondary" title="Print or save as PDF" onClick={() => {
              const win = window.open("", "_blank");
              if (win) {
                win.document.write(`<!DOCTYPE html><html><head><title>Minutes – Revision ${row.revision}</title><style>body{font-family:sans-serif;max-width:800px;margin:2rem auto;padding:1rem}h1{font-size:1.3rem}pre{white-space:pre-wrap;font-family:inherit}</style></head><body><h1>${eventDetails?.title || meeting.meeting_type} – Minutes (Revision ${row.revision})</h1><p><em>Status: ${row.status}</em></p><pre>${row.content.replace(/</g, "&lt;").replace(/>/g, "&gt;")}</pre><p style="margin-top:2rem;font-size:.8rem;color:#666">Generated by EvenSpace · ${new Date().toLocaleString()}</p></body></html>`);
                win.document.close();
                win.print();
              }
            }}><Printer size={14} /> Print / PDF</button>
          )}</div></article>)}{!minutes.length && <p className="meeting-empty">No minutes recorded yet.</p>}</div>
        </section>
        <section className="meeting-card"><div className="meeting-section-title"><div><h2>Decisions</h2><p>Numbered resolutions</p></div></div>
          <form className="meeting-inline-form" onSubmit={(event) => void submit(event, () => api(`${base}/decisions`, { method: "POST", body: JSON.stringify({ title: new FormData(event.currentTarget).get("title"), details: new FormData(event.currentTarget).get("details") }) }), "Decision recorded.")}><input name="title" required placeholder="Decision title" /><input name="details" required placeholder="Resolution details" /><button className="button button-primary" disabled={busy}>Add</button></form>
          <div className="meeting-record-list">{decisions.map((row) => <article className="meeting-record" key={row.id}><div><strong>#{row.decision_number} · {row.title}</strong><small>{row.details} · {row.status}</small></div>{row.status === "proposed" && <button className="button button-secondary" onClick={() => void submit(new Event("submit") as unknown as FormEvent, () => api(`${base}/decisions/${row.id}/resolve`, { method: "POST", body: JSON.stringify({ result: "adopted" }) }), "Decision adopted.")}>Adopt</button>}</article>)}{!decisions.length && <p className="meeting-empty">Decisions will appear here.</p>}</div>
        </section>
        <section className="meeting-card"><div className="meeting-section-title"><div><h2>Action items</h2><p>Track ownership and completion</p></div></div>
          <form className="meeting-inline-form" onSubmit={(event) => void submit(event, () => api(`${base}/action-items`, { method: "POST", body: JSON.stringify({ title: new FormData(event.currentTarget).get("title") }) }), "Action item added.")}><input name="title" required placeholder="Action to follow up" /><button className="button button-primary" disabled={busy}>Add</button></form>
          <div className="meeting-record-list">{actions.map((row) => <div className="meeting-record" key={row.id}><div><strong>{row.title}</strong><small>{row.status.replace("_", " ")}</small></div>{row.status !== "completed" && row.status !== "cancelled" && <button className="button button-secondary" onClick={() => void submit(new Event("submit") as unknown as FormEvent, () => api(`${base}/action-items/${row.id}/status`, { method: "POST", body: JSON.stringify({ status: row.status === "open" ? "in_progress" : "completed" }) }), "Action status updated.")}>{row.status === "open" ? "Start" : "Complete"}</button>}</div>)}{!actions.length && <p className="meeting-empty">No actions assigned yet.</p>}</div>
        </section>
        </>}
      </div> : <section className="meeting-card meeting-placeholder"><CalendarDays size={28} /><h2>Select or create a meeting</h2><p>Choose a meeting on the left to open its institutional record.</p></section>}
    </div>
    <footer className="footer"><span>EVENSPACE</span><span>Institutional meeting records</span></footer>
  </main>;
}

function MeetingQrCode({ value }: { value: string }) {
  const target = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let active = true;
    void import("@zxing/browser").then(({ BrowserQRCodeSvgWriter }) => {
      if (active && target.current) target.current.replaceChildren(new BrowserQRCodeSvgWriter().write(value, 240, 240));
    });
    return () => { active = false; };
  }, [value]);
  return <div className="meeting-qr-image" ref={target} aria-label="Meeting registration QR code" />;
}
