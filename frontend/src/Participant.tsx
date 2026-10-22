import { useEffect, useRef, useState, type FormEvent } from "react";
import { ArrowLeft, CalendarDays, CheckCircle2, Copy, Printer, QrCode, Search, ShieldCheck, Ticket } from "lucide-react";

const API_BASE = (import.meta.env.VITE_API_BASE_URL || "http://localhost:8000/api/v1").replace(/\/$/, "");
type TicketType = { id: string; name: string; description: string | null; price: string; capacity: number | null };
type EventInfo = {
  id: string; title: string; description: string | null; category: string;
  start_at: string; end_at: string; timezone: string; registration_close_at: string | null;
  ticket_types: TicketType[];
};
type DiscoverableEvent = EventInfo;
type TicketInfo = {
  ticket_id: string; event_id: string; event_title: string; start_at: string; end_at: string;
  timezone: string; ticket_type_name: string; attendee_name: string; status: string;
};
type IssuedTicket = TicketInfo & { credential: string };

async function readError(response: Response): Promise<string> {
  const body = await response.json().catch(() => null) as { detail?: string } | null;
  return body?.detail ?? `Request failed (${response.status})`;
}

function TicketQr({ value }: { value: string }) {
  const target = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let mounted = true;
    void import("@zxing/browser").then(({ BrowserQRCodeSvgWriter }) => {
      if (!mounted || !target.current) return;
      target.current.replaceChildren(new BrowserQRCodeSvgWriter().write(value, 240, 240));
    });
    return () => { mounted = false; };
  }, [value]);
  return <div className="ticket-qr" ref={target} aria-label="Ticket QR code" />;
}

export default function Participant({
  onGate,
  onEvents,
  onMeetings,
}: {
  onGate: () => void;
  onEvents?: () => void;
  onMeetings?: () => void;
}) {
  const [publicEvents, setPublicEvents] = useState<DiscoverableEvent[]>([]);
  const [eventsLoading, setEventsLoading] = useState(true);
  const [eventSearch, setEventSearch] = useState("");
  const [eventId, setEventId] = useState("");
  const [eventInfo, setEventInfo] = useState<EventInfo | null>(null);
  const [ticketTypeId, setTicketTypeId] = useState("");
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [lookupCredential, setLookupCredential] = useState("");
  const [ticket, setTicket] = useState<IssuedTicket | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [messageTone, setMessageTone] = useState<"error" | "success" | "info">("info");
  const idempotencyKey = useRef<string | null>(null);

  const freeTypes = eventInfo?.ticket_types.filter((item) => Number(item.price) === 0) ?? [];

  useEffect(() => {
    let active = true;
    void fetch(`${API_BASE}/public/events`).then(async (response) => {
      if (!response.ok) throw new Error(await readError(response));
      return await response.json() as DiscoverableEvent[];
    }).then((rows) => { if (active) setPublicEvents(rows); })
      .catch((error: unknown) => { if (active) { setMessage(error instanceof Error ? error.message : "Could not load public events."); setMessageTone("error"); } })
      .finally(() => { if (active) setEventsLoading(false); });
    return () => { active = false; };
  }, []);

  async function selectEvent(id: string) {
    idempotencyKey.current = null;
    setBusy(true); setMessage(""); setTicket(null);
    try {
      const response = await fetch(`${API_BASE}/public/events/${encodeURIComponent(id.trim())}`);
      if (!response.ok) throw new Error(await readError(response));
      const data = await response.json() as EventInfo;
      setEventInfo(data);
      setEventId(id);
      setTicketTypeId(data.ticket_types.find((item) => Number(item.price) === 0)?.id ?? "");
      setMessage("");
    } catch (error) {
      setEventInfo(null);
      setMessage(error instanceof Error ? error.message : "Could not load this event.");
      setMessageTone("error");
    } finally { setBusy(false); }
  }

  async function loadEvent(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await selectEvent(eventId);
  }

  const visibleEvents = publicEvents.filter((event) =>
    `${event.title} ${event.category} ${event.description ?? ""}`.toLocaleLowerCase().includes(eventSearch.trim().toLocaleLowerCase()),
  );

  async function register(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!eventInfo || !ticketTypeId) return;
    setBusy(true); setMessage("");
    idempotencyKey.current ??= crypto.randomUUID();
    try {
      const response = await fetch(`${API_BASE}/public/events/${encodeURIComponent(eventInfo.id)}/registrations`, {
        method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey.current },
        body: JSON.stringify({ full_name: fullName, email, ticket_type_id: ticketTypeId }),
      });
      if (!response.ok) throw new Error(await readError(response));
      const issued = await response.json() as {
        ticket_id: string; event_id: string; ticket_credential: string; full_name: string; status: string;
      };
      setTicket({
        ticket_id: issued.ticket_id, event_id: issued.event_id, event_title: eventInfo.title,
        start_at: eventInfo.start_at, end_at: eventInfo.end_at, timezone: eventInfo.timezone,
        ticket_type_name: eventInfo.ticket_types.find((item) => item.id === ticketTypeId)?.name ?? "Ticket",
        attendee_name: issued.full_name, status: issued.status, credential: issued.ticket_credential,
      });
      setLookupCredential(issued.ticket_credential);
      idempotencyKey.current = null;
      setMessage("Your registration is confirmed. Save the QR code or keep the ticket credential somewhere private.");
      setMessageTone("success");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Registration could not be completed. You can safely retry.");
      setMessageTone("error");
    } finally { setBusy(false); }
  }

  async function lookup(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setMessage("");
    try {
      const response = await fetch(`${API_BASE}/public/tickets/lookup`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ credential: lookupCredential.trim() }),
      });
      if (!response.ok) throw new Error(await readError(response));
      const data = await response.json() as TicketInfo;
      setTicket({ ...data, credential: lookupCredential.trim() });
      setMessage("Ticket loaded. Anyone with this credential can use it, so keep it private.");
      setMessageTone("success");
    } catch (error) {
      setTicket(null); setMessage(error instanceof Error ? error.message : "Could not find an active ticket.");
      setMessageTone("error");
    } finally { setBusy(false); }
  }

  async function copyCredential() {
    if (!ticket) return;
    try {
      await navigator.clipboard.writeText(ticket.credential);
      setMessage("Ticket credential copied."); setMessageTone("success");
    } catch {
      setMessage("Clipboard access is unavailable. You can select and copy the credential below."); setMessageTone("info");
    }
  }

  return <main className="shell participant-shell">
    <header className="topbar">
      <a className="brand" href="#participant-top" aria-label="EvenSpace home"><span className="brand-mark"><span /></span><span>evenspace</span></a>
      <div className="topbar-actions">
        {onEvents && <button className="view-switch" type="button" onClick={onEvents}>Events</button>}
        {onMeetings && <button className="view-switch" type="button" onClick={onMeetings}>Meetings</button>}
        <button className="view-switch" type="button" onClick={onGate}>Gate scanner</button>
      </div>
    </header>
    <section className="intro" id="participant-top">
      <div className="eyebrow"><span className="eyebrow-dot" /> YOUR EVENSPACE TICKETS</div>
      <h1>Good plans, <span>checked in.</span></h1>
          <p>Browse public events, register for a free ticket, or retrieve an existing ticket with its private credential.</p>
    </section>
    {message && <div className={`notice notice-${messageTone}`} role={messageTone === "error" ? "alert" : "status"}>
      {messageTone === "success" ? <CheckCircle2 size={18} /> : <ShieldCheck size={18} />}<span>{message}</span>
    </div>}

    {ticket ? <section className="participant-ticket card" aria-label="Your ticket">
      <div className="participant-ticket-heading">
        <span className="event-label"><Ticket size={15} /> {ticket.status.toUpperCase()} TICKET</span>
        <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
          <span className="ticket-type-pill">{ticket.ticket_type_name}</span>
          <button className="button button-secondary no-print" type="button" onClick={() => window.print()} title="Print or save as PDF">
            <Printer size={14} /> Print
          </button>
        </div>
      </div>
      <div className="participant-ticket-content">
        <div><h2>{ticket.event_title}</h2><p className="ticket-holder">Admit one · {ticket.attendee_name}</p>
          <div className="event-meta"><span><CalendarDays size={15} /> {new Date(ticket.start_at).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })}</span></div>
          <p className="ticket-event-id">Event ID · {ticket.event_id}</p></div>
        <TicketQr value={ticket.credential} />
      </div>
      <div className="ticket-secret no-print"><div><strong>Private ticket credential</strong><span>This code grants admission. Do not share it publicly.</span></div>
        <button className="button button-secondary" type="button" onClick={() => void copyCredential()}><Copy size={15} /> Copy</button>
        <code>{ticket.credential}</code>
      </div>
      <button className="text-button ticket-reset no-print" type="button" onClick={() => { setTicket(null); setMessage(""); }}>Back to event and ticket lookup</button>
    </section> : <div className="participant-grid">
      <section className="participant-card card">
        <div className="section-heading"><div className="heading-icon"><Search size={19} /></div><div><h2>Find an event</h2><p>Browse upcoming public events.</p></div></div>
        <label className="field"><span>Search events</span><input type="search" value={eventSearch} onChange={(event) => setEventSearch(event.target.value)} placeholder="Search by title or category" /></label>
        <div className="discovery-event-list" aria-live="polite">
          {eventsLoading && <p className="field-help">Loading upcoming events…</p>}
          {!eventsLoading && visibleEvents.map((event) => <article className="discovery-event" key={event.id}>
            <div><span className="event-label"><CalendarDays size={13} /> {event.category}</span><h3>{event.title}</h3><p>{new Date(event.start_at).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })} · {event.timezone}</p></div>
            <button className="button button-secondary" type="button" disabled={busy} onClick={() => void selectEvent(event.id)}>{eventInfo?.id === event.id ? "Selected" : "View event"}</button>
          </article>)}
          {!eventsLoading && !visibleEvents.length && <p className="field-help">{publicEvents.length ? "No events match your search." : "No upcoming public events are open for registration."}</p>}
        </div>
        <details className="event-id-lookup"><summary>Have an event ID?</summary><form onSubmit={(event) => void loadEvent(event)}>
          <label className="field"><span>Event ID</span><input required value={eventId} onChange={(event) => setEventId(event.target.value)} placeholder="Paste the event ID" /></label>
          <button className="button button-primary full-width" disabled={busy || !eventId.trim()} type="submit">{busy ? "Loading event…" : "View event"}</button>
        </form></details>
        {eventInfo && <div className="public-event-summary">
          <span className="event-label"><CalendarDays size={14} /> {eventInfo.category}</span><h3>{eventInfo.title}</h3>
          {eventInfo.description && <p>{eventInfo.description}</p>}
          <div className="event-meta"><span>{new Date(eventInfo.start_at).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })}</span><span>{eventInfo.timezone}</span></div>
          <div className="ticket-type-list">{eventInfo.ticket_types.map((item) => <div className="ticket-type-option" key={item.id}>
            <span><strong>{item.name}</strong>{item.description && <small>{item.description}</small>}</span>
            <span>{Number(item.price) === 0 ? "Free" : `KES ${Number(item.price).toLocaleString("en-KE")}`}</span>
          </div>)}</div>
          {freeTypes.length ? <form className="participant-register" onSubmit={(event) => void register(event)}>
            <label className="field"><span>Ticket type</span><select required value={ticketTypeId} onChange={(event) => { idempotencyKey.current = null; setTicketTypeId(event.target.value); }}>
              {freeTypes.map((item) => <option key={item.id} value={item.id}>{item.name} · Free</option>)}
            </select></label>
            <label className="field"><span>Your full name</span><input required minLength={1} maxLength={200} value={fullName} onChange={(event) => { idempotencyKey.current = null; setFullName(event.target.value); }} autoComplete="name" /></label>
            <label className="field"><span>Email address</span><input required type="email" value={email} onChange={(event) => { idempotencyKey.current = null; setEmail(event.target.value); }} autoComplete="email" /></label>
            <button className="button button-primary full-width" disabled={busy || !ticketTypeId} type="submit">{busy ? "Reserving your ticket…" : "Register for free"}</button>
          </form> : <p className="field-help">This event has no free tickets available. Paid checkout is not enabled yet.</p>}
          {eventInfo.ticket_types.some((item) => Number(item.price) > 0) && <p className="field-help">Paid ticket checkout is currently unavailable. No payment will be taken.</p>}
        </div>}
      </section>

      <section className="participant-card card">
        <div className="section-heading"><div className="heading-icon scan-icon"><QrCode size={19} /></div><div><h2>Retrieve a ticket</h2><p>Use the private credential from your confirmation email.</p></div></div>
        <form onSubmit={(event) => void lookup(event)}>
          <label className="field"><span>Ticket credential</span><input required pattern="[0-9a-f]{64}" minLength={64} maxLength={64} value={lookupCredential} onChange={(event) => setLookupCredential(event.target.value)} placeholder="64-character private code" autoComplete="off" autoCapitalize="off" spellCheck={false} /></label>
          <button className="button button-primary full-width" disabled={busy || lookupCredential.trim().length !== 64} type="submit">{busy ? "Finding ticket…" : "Show my ticket"}</button>
        </form>
        <div className="security-note"><ShieldCheck size={16} /><span>Credentials are kept in this page's memory and are not saved to browser storage.</span></div>
      </section>
    </div>}
    <footer className="footer"><span>EVENSPACE</span><span>One ticket · One admission</span></footer>
  </main>;
}
