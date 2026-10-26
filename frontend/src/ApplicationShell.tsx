import { useEffect, useState, type ReactNode } from "react";
import { CalendarDays, LayoutDashboard, LogOut, QrCode, Settings as SettingsIcon, Ticket, Users } from "lucide-react";
import { api } from "./api";

export type AppModule = "events" | "meetings" | "scanner" | "participant" | "settings";

const modules: Array<{ id: AppModule; label: string; path: string; icon: typeof CalendarDays }> = [
  { id: "events", label: "Events", path: "/events", icon: CalendarDays },
  { id: "meetings", label: "Meetings", path: "/meetings", icon: Users },
  { id: "scanner", label: "Gate Scanner", path: "/gate-scanner", icon: QrCode },
  { id: "participant", label: "My Tickets", path: "/my-tickets", icon: Ticket },
  { id: "settings", label: "Settings", path: "/settings", icon: SettingsIcon },
];

const submodules: Record<AppModule, Array<{ label: string; hash: string }>> = {
  events: [{ label: "Event list", hash: "#event-list" }, { label: "Registrations & attendance", hash: "#event-registrations" }, { label: "Scanner devices", hash: "#event-scanners" }],
  meetings: [{ label: "Meeting list", hash: "#meeting-list" }, { label: "Attendees", hash: "#attendees" }, { label: "Agenda & minutes", hash: "#records" }, { label: "Invitations & QR", hash: "#invitations" }, { label: "Attendance", hash: "#checkin" }],
  scanner: [{ label: "Connect a scanner", hash: "#connect-scanner" }, { label: "Scan tickets", hash: "#scan-ticket" }, { label: "Recent scans", hash: "#scan-history" }],
  participant: [{ label: "Browse events", hash: "#browse-events" }, { label: "Ticket details", hash: "#ticket-details" }],
  settings: [{ label: "Account & security", hash: "#account-security" }, { label: "Workspace members", hash: "#workspace-settings" }, { label: "Email templates", hash: "#notification-settings" }],
};

export default function ApplicationShell({ module, navigate, children }: {
  module: AppModule;
  navigate: (path: string) => void;
  children: ReactNode;
}) {
  const [email, setEmail] = useState("");
  const [currentHash, setCurrentHash] = useState(window.location.hash);
  const [accountMessage, setAccountMessage] = useState("");
  useEffect(() => { void api<{ email: string }>("/auth/me").then((user) => setEmail(user.email)).catch(() => setEmail("")); }, []);
  useEffect(() => {
    const update = (event: Event) => {
      const detail = (event as CustomEvent<string>).detail;
      setCurrentHash(detail?.includes("#") ? detail.slice(detail.indexOf("#")) : window.location.hash);
    };
    window.addEventListener("evenspace:navigate", update);
    return () => window.removeEventListener("evenspace:navigate", update);
  }, []);

  async function signOut() {
    setAccountMessage("");
    try { await api("/auth/logout", { method: "POST" }); setEmail(""); navigate("/meetings"); }
    catch (error) { setAccountMessage(error instanceof Error ? error.message : "Could not sign out."); }
  }

  function navigateToSection(hash: string) {
    const meetingId = module === "meetings" ? window.location.pathname.split("/")[2] : "";
    const section = hash.slice(1);
    const meetingPath = section === "records" ? "agenda" : section === "checkin" ? "attendance" : section;
    const path = meetingId && /^[0-9a-f-]{36}$/i.test(meetingId)
      ? `/meetings/${meetingId}/${meetingPath}`
      : `${modules.find((item) => item.id === module)?.path}${hash}`;
    navigate(path);
    window.setTimeout(() => document.getElementById(section)?.scrollIntoView({ behavior: "smooth", block: "start" }), 0);
  }

  return <div className="app-shell">
    <header className="app-topbar">
      <button className="app-brand" type="button" onClick={() => navigate("/meetings")} aria-label="EvenSpace home">
        <span className="brand-mark"><span /></span><span>EvenSpace</span>
      </button>
      <div className="app-topbar-context"><LayoutDashboard size={16} /> Event & meeting operations</div>
      <div className="app-account">{email && <><span title={email}>{email}</span><button type="button" onClick={() => void signOut()}><LogOut size={15} /> Sign out</button></>}</div>
    </header>
    {accountMessage && <div className="app-account-error" role="alert">{accountMessage}</div>}
    <div className="app-layout">
      <aside className="app-sidebar" aria-label="Application modules">
        <span className="app-sidebar-label">WORKSPACE</span>
        <nav className="app-module-nav">
          {modules.map(({ id, label, path, icon: Icon }) => <button key={id} className={module === id ? "active" : ""} type="button" aria-current={module === id ? "page" : undefined} onClick={() => navigate(path)}>
            <Icon size={17} /><span>{label}</span>
          </button>)}
        </nav>
        <div className="app-subnav"><span className="app-sidebar-label">IN THIS MODULE</span>
          {submodules[module].map(({ label, hash }) => <button className={`app-subnav-item${currentHash === hash ? " current" : ""}`} key={label} type="button" onClick={() => navigateToSection(hash)}>{label}</button>)}
        </div>
      </aside>
      <div className="app-content">{children}</div>
    </div>
  </div>;
}
