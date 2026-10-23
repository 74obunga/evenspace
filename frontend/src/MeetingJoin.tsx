import { useEffect, useState, type FormEvent } from "react";
import { CalendarDays, CheckCircle2, ShieldCheck, Users } from "lucide-react";
import { API_BASE } from "./apiBase";

type MeetingInfo = { meeting_id: string; meeting_type: string; event_title: string; starts_at: string; timezone: string; meeting_mode: "physical" | "online" };
type MeetingJoinResult = { join_url: string | null };

async function request<T>(url: string, body: object): Promise<{ data: T; status: number }> {
  const response = await fetch(`${API_BASE}${url}`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const data = await response.json().catch(() => null) as (T & { detail?: string }) | null;
  if (!response.ok) throw new Error(data?.detail ?? `Request failed (${response.status})`);
  return { data: data as T, status: response.status };
}

export default function MeetingJoin({ meetingId, token }: { meetingId: string; token: string }) {
  const [info, setInfo] = useState<MeetingInfo | null>(null);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [attendeeType, setAttendeeType] = useState<"staff" | "guest">("staff");
  const [organization, setOrganization] = useState("");
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

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      const result = await request<MeetingJoinResult>(`/public/meetings/${encodeURIComponent(meetingId)}/join`, {
        token, full_name: name, email, phone, attendee_type: attendeeType,
        organization: organization.trim() || null,
      });
      setOnlineJoinUrl(result.data.join_url);
      setJoined(true);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Your registration could not be saved. Please retry.");
    } finally { setBusy(false); }
  }

  return <main className="meeting-join-shell">
    <header className="meeting-join-header"><a className="brand" href="/"><span className="brand-mark"><span /></span><span>evenspace</span></a><span className="meeting-tag"><Users size={14} /> MEETING REGISTRATION</span></header>
    <section className="meeting-join-card card">
      {info ? <>
        <span className="meeting-kicker"><CalendarDays size={15} /> {info.meeting_type}</span>
        <h1>{joined ? "You’re on the list." : `Join ${info.event_title}`}</h1>
        <p className="meeting-join-subtitle">{new Date(info.starts_at).toLocaleString([], { dateStyle: "full", timeStyle: "short" })} · {info.timezone}</p>
        {joined ? <div className="meeting-join-confirmation" role="status"><CheckCircle2 size={22} /><div><strong>Registration confirmed</strong><span>Your details have been added to the meeting attendee list.</span>{onlineJoinUrl && <a className="button button-primary" href={onlineJoinUrl} target="_blank" rel="noreferrer">Join online meeting</a>}</div></div> : <>
          <p className="meeting-join-copy">Complete this form to join the attendee list. Your contact details will only be visible to the meeting organizers.</p>
          {error && <div className="notice notice-error" role="alert">{error}</div>}
          <form className="meeting-join-form" onSubmit={(event) => void submit(event)}>
            <label className="field"><span>Full name</span><input required minLength={1} maxLength={200} autoComplete="name" value={name} onChange={(event) => setName(event.target.value)} /></label>
            <div className="meeting-join-fields">
              <label className="field"><span>Email address</span><input required type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} /></label>
              <label className="field"><span>Phone number</span><input required type="tel" minLength={7} maxLength={24} autoComplete="tel" placeholder="+254 7XX XXX XXX" value={phone} onChange={(event) => setPhone(event.target.value)} /></label>
            </div>
            <fieldset className="attendee-kind"><legend>I am joining as</legend>
              <label className={attendeeType === "staff" ? "selected" : ""}><input type="radio" name="attendee-type" value="staff" checked={attendeeType === "staff"} onChange={() => setAttendeeType("staff")} /><span>Staff member</span></label>
              <label className={attendeeType === "guest" ? "selected" : ""}><input type="radio" name="attendee-type" value="guest" checked={attendeeType === "guest"} onChange={() => setAttendeeType("guest")} /><span>Guest</span></label>
            </fieldset>
            <label className="field"><span>{attendeeType === "staff" ? "Department or organization" : "Organization (optional)"}</span><input maxLength={200} value={organization} onChange={(event) => setOrganization(event.target.value)} /></label>
            <button className="button button-primary full-width" disabled={busy} type="submit">{busy ? "Joining meeting…" : "Join meeting"}</button>
          </form>
          <div className="security-note"><ShieldCheck size={16} /><span>Agendas, minutes, and internal meeting records are not shared on this page.</span></div>
        </>}
      </> : error ? <div className="meeting-join-error"><ShieldCheck size={24} /><h1>This meeting link is unavailable</h1><p>{error}</p><span>Ask the meeting organizer for a current QR code.</span></div> : <div className="meeting-join-loading" role="status">Checking meeting link…</div>}
    </section>
    <footer className="footer"><span>EVENSPACE</span><span>Secure meeting registration</span></footer>
  </main>;
}
