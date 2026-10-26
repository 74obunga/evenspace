import { useEffect, useRef, useState, type FormEvent, type PointerEvent } from "react";
import { CalendarDays, CheckCircle2, MapPin, ShieldCheck, Users } from "lucide-react";
import { API_BASE } from "./apiBase";

type MeetingInfo = { meeting_id: string; meeting_type: string; event_title: string; starts_at: string; timezone: string; meeting_mode: "physical" | "online" };
type MeetingJoinResult = { join_url: string | null };
type CapturedLocation = { latitude: number; longitude: number; accuracy_m: number; captured_at: string };
type LocationState = "idle" | "requesting" | "captured" | "denied" | "unavailable" | "failed";

async function request<T>(url: string, body: object): Promise<{ data: T; status: number }> {
  const response = await fetch(`${API_BASE}${url}`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const data = await response.json().catch(() => null) as (T & { detail?: string }) | null;
  if (!response.ok) throw new Error(data?.detail ?? `Request failed (${response.status})`);
  return { data: data as T, status: response.status };
}

function SignaturePad({ value, onChange }: { value: string; onChange: (data: string) => void }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const drawing = useRef(false);

  function point(event: PointerEvent<HTMLCanvasElement>) {
    const canvas = event.currentTarget;
    const rect = canvas.getBoundingClientRect();
    return { x: (event.clientX - rect.left) * canvas.width / rect.width, y: (event.clientY - rect.top) * canvas.height / rect.height };
  }

  function start(event: PointerEvent<HTMLCanvasElement>) {
    const canvas = canvasRef.current;
    if (!canvas) return;
    event.preventDefault();
    canvas.setPointerCapture(event.pointerId);
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const p = point(event);
    ctx.strokeStyle = "#215b3a"; ctx.lineWidth = 5; ctx.lineCap = "round"; ctx.lineJoin = "round";
    ctx.beginPath(); ctx.moveTo(p.x, p.y); ctx.lineTo(p.x + 0.1, p.y + 0.1); ctx.stroke();
    drawing.current = true;
  }

  function move(event: PointerEvent<HTMLCanvasElement>) {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx || !drawing.current) return;
    event.preventDefault();
    const p = point(event);
    ctx.lineTo(p.x, p.y); ctx.stroke();
  }

  function stop() {
    drawing.current = false;
    const canvas = canvasRef.current;
    if (canvas) onChange(canvas.toDataURL("image/png"));
  }

  function clear() {
    const canvas = canvasRef.current;
    canvas?.getContext("2d")?.clearRect(0, 0, canvas.width, canvas.height);
    onChange("");
  }

  return <div className="signature-pad-wrap">
    <canvas ref={canvasRef} className="signature-pad" width={900} height={300} aria-label="Draw your signature here"
      onPointerDown={start} onPointerMove={move} onPointerUp={stop} onPointerCancel={stop} />
    <div className="signature-pad-footer"><span>{value ? "Signature captured" : "Use your finger, stylus, or mouse to sign"}</span>
      <button className="meeting-link" type="button" onClick={clear} disabled={!value}>Clear signature</button>
    </div>
  </div>;
}

export default function MeetingJoin({ meetingId, token }: { meetingId: string; token: string }) {
  const [info, setInfo] = useState<MeetingInfo | null>(null);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [attendeeType, setAttendeeType] = useState<"speaker" | "secretary" | "chairperson" | "member_delegate">("member_delegate");
  const [organization, setOrganization] = useState("");
  const [signature, setSignature] = useState("");
  const [location, setLocation] = useState<CapturedLocation | null>(null);
  const [locationState, setLocationState] = useState<LocationState>("idle");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [joined, setJoined] = useState(false);
  const [onlineJoinUrl, setOnlineJoinUrl] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    void request<MeetingInfo>(`/public/meetings/${encodeURIComponent(meetingId)}/join-info`, { token })
      .then(({ data }) => { if (active) setInfo(data); })
      .catch((reason: unknown) => { if (active) setError(reason instanceof Error ? reason.message : "This meeting link is invalid or closed."); });
    return () => { active = false; };
  }, [meetingId, token]);

  function captureLocation() {
    setLocation(null);
    if (!navigator.geolocation) { setLocationState("unavailable"); return; }
    setLocationState("requesting");
    navigator.geolocation.getCurrentPosition((position) => {
      const { latitude, longitude, accuracy } = position.coords;
      if (!Number.isFinite(latitude) || latitude < -90 || latitude > 90 || !Number.isFinite(longitude) || longitude < -180 || longitude > 180 || !Number.isFinite(accuracy) || accuracy < 0 || accuracy > 100000) {
        setLocationState("failed");
        return;
      }
      setLocation({ latitude: position.coords.latitude, longitude: position.coords.longitude,
        accuracy_m: accuracy, captured_at: new Date(position.timestamp || Date.now()).toISOString() });
      setLocationState("captured");
    }, (reason) => {
      setLocationState(reason.code === reason.PERMISSION_DENIED ? "denied" : reason.code === reason.POSITION_UNAVAILABLE ? "unavailable" : "failed");
    }, { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 });
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!signature) { setError("Add your signature before joining the meeting."); return; }
    setBusy(true); setError("");
    try {
      const result = await request<MeetingJoinResult>(`/public/meetings/${encodeURIComponent(meetingId)}/join`, {
        token, full_name: name, email, phone, attendee_type: attendeeType,
        organization: organization.trim() || null,
        signature_data: signature,
        gps_latitude: location?.latitude ?? null,
        gps_longitude: location?.longitude ?? null,
        gps_accuracy_m: location?.accuracy_m ?? null,
        gps_captured_at: location?.captured_at ?? null,
      });
      setOnlineJoinUrl(result.data.join_url);
      setJoined(true);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Your registration could not be saved. Please retry.");
    } finally { setBusy(false); }
  }

  const locationMessage: Record<LocationState, string> = {
    idle: "Not shared. Location is optional.", requesting: "Requesting your location…",
    captured: location ? `Captured with ±${Math.round(location.accuracy_m)} m reported accuracy.` : "Location captured.",
    denied: "Location permission was denied. You can still register without it.",
    unavailable: "Location is unavailable on this device. You can still register.",
    failed: "Location could not be captured. You can still register without it.",
  };

  return <main className="meeting-join-shell">
    <header className="meeting-join-header"><a className="brand" href="/"><span className="brand-mark"><span /></span><span>evenspace</span></a><span className="meeting-tag"><Users size={14} /> MEETING REGISTRATION</span></header>
    <section className="meeting-join-card card">
      {info ? <>
        <span className="meeting-kicker"><CalendarDays size={15} /> {info.meeting_type}</span>
        <h1>{joined ? "You’re on the list." : `Join ${info.event_title}`}</h1>
        <p className="meeting-join-subtitle">{new Date(info.starts_at).toLocaleString([], { dateStyle: "full", timeStyle: "short" })} · {info.timezone}</p>
        {joined ? <div className="meeting-join-confirmation" role="status"><CheckCircle2 size={22} /><div><strong>Registration confirmed</strong><span>Your details have been added to the meeting attendee list.</span>{onlineJoinUrl && <a className="button button-primary" href={onlineJoinUrl} target="_blank" rel="noreferrer">Join online meeting</a>}</div></div> : <>
          <p className="meeting-join-copy">Complete this form to join the attendee list. Your contact details and signature, plus any location you choose to share, are visible only to meeting organizers. Organizers can remove signature and location data while keeping the attendance record.</p>
          {error && <div className="notice notice-error" role="alert">{error}</div>}
          <form className="meeting-join-form" onSubmit={(event) => void submit(event)}>
            <label className="field"><span>Full name</span><input required minLength={1} maxLength={200} autoComplete="name" value={name} onChange={(event) => setName(event.target.value)} /></label>
            <div className="meeting-join-fields">
              <label className="field"><span>Email address</span><input required type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} /></label>
              <label className="field"><span>Phone number</span><input required type="tel" minLength={7} maxLength={24} autoComplete="tel" placeholder="+254 7XX XXX XXX" value={phone} onChange={(event) => setPhone(event.target.value)} /></label>
            </div>
            <label className="field"><span>Attendee role</span><select value={attendeeType} onChange={(event) => setAttendeeType(event.target.value as typeof attendeeType)}>
              <option value="speaker">Speaker</option><option value="secretary">Secretary</option><option value="chairperson">Chairperson</option><option value="member_delegate">Member / Delegate</option>
            </select></label>
            <label className="field"><span>Department or organization (optional)</span><input maxLength={200} value={organization} onChange={(event) => setOrganization(event.target.value)} /></label>
            <section className="registration-consent-section" aria-labelledby="location-title">
              <div className="registration-section-heading"><MapPin size={17} /><div><h2 id="location-title">Location (optional)</h2><p>Share your location with meeting organizers if you choose.</p></div></div>
              <p className="field-help">It may help organizers understand where registrations were submitted. It is not proof of identity or attendance.</p>
              <button className="button button-secondary" type="button" onClick={captureLocation} disabled={locationState === "requesting"}>
                <MapPin size={15} /> {locationState === "requesting" ? "Capturing…" : locationState === "captured" ? "Capture again" : "Capture my location"}
              </button>
              <p className={`location-status location-${locationState}`} role="status">{locationMessage[locationState]}</p>
            </section>
            <section className="registration-consent-section" aria-labelledby="signature-title">
              <div className="registration-section-heading"><ShieldCheck size={17} /><div><h2 id="signature-title">Digital signature <span aria-hidden="true">*</span></h2><p>Sign below to confirm your registration.</p></div></div>
              <SignaturePad value={signature} onChange={setSignature} />
              <p className="field-help">Your drawn signature records this sign-off; it does not verify identity or guarantee legal enforceability.</p>
              {!signature && <p className="signature-required" role="status">A signature is required to enable registration.</p>}
            </section>
            <button className="button button-primary full-width" disabled={busy || !signature} type="submit">{busy ? "Joining meeting…" : "Join meeting"}</button>
          </form>
          <div className="security-note"><ShieldCheck size={16} /><span>Agendas, minutes, and internal meeting records are not shared on this page.</span></div>
        </>}
      </> : error ? <div className="meeting-join-error"><ShieldCheck size={24} /><h1>This meeting link is unavailable</h1><p>{error}</p><span>Ask the meeting organizer for a current QR code.</span></div> : <div className="meeting-join-loading" role="status">Checking meeting link…</div>}
    </section>
    <footer className="footer"><span>EVENSPACE</span><span>Secure meeting registration</span></footer>
  </main>;
}
