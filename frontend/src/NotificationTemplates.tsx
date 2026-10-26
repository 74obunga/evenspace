import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Mail, RefreshCw, Save } from "lucide-react";
import { api } from "./api";

type TemplateItem = {
  key: string;
  channel: string;
  subject_template: string;
  body_template: string;
  enabled: boolean;
};

const TEMPLATE_INFO: Record<string, { label: string; description: string; vars: string[] }> = {
  registration_confirmation: {
    label: "Registration Confirmation",
    description: "Sent immediately when an attendee completes registration.",
    vars: ["{full_name}", "{event_title}", "{event_start}"],
  },
  meeting_invitation: {
    label: "Meeting Invitation",
    description: "Sent to members invited to internal institutional meetings.",
    vars: ["{full_name}", "{meeting_type}", "{event_title}", "{event_start}"],
  },
  ticket_issuance: {
    label: "Ticket Issuance",
    description: "Delivers admission ticket credentials to confirmed participants.",
    vars: ["{full_name}", "{event_title}", "{event_start}", "{ticket_credential}"],
  },
  event_reminder: {
    label: "Event Reminder",
    description: "Dispatched automatically to confirmed attendees prior to event start.",
    vars: ["{full_name}", "{event_title}", "{event_start}"],
  },
  event_update: {
    label: "Event Schedule Update",
    description: "Sent to attendees when an event's schedule or venue is modified.",
    vars: ["{full_name}", "{event_title}", "{change_summary}"],
  },
  event_cancellation: {
    label: "Event Cancellation Notice",
    description: "Sent to attendees when an organizer cancels an event.",
    vars: ["{full_name}", "{event_title}", "{reason}"],
  },
  organizer_alert: {
    label: "Organizer Alert",
    description: "Notifies event managers of gate assignments or operational updates.",
    vars: ["{alert_message}", "{event_title}"],
  },
};

export default function NotificationTemplates({
  workspaceId,
  canManage,
}: {
  workspaceId: string;
  canManage: boolean;
}) {
  const [templates, setTemplates] = useState<TemplateItem[]>([]);
  const [activeKey, setActiveKey] = useState<string>("");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ tone: "success" | "error"; text: string } | null>(null);

  const reloadTemplates = useCallback(async () => {
    if (!workspaceId) { setTemplates([]); return; }
    setLoading(true);
    try {
      const rows = await api<TemplateItem[]>(`/workspaces/${workspaceId}/notifications/templates`);
      setTemplates(rows);
      if (!activeKey && rows.length > 0) {
        selectTemplate(rows[0]);
      } else if (activeKey) {
        const found = rows.find((r) => r.key === activeKey);
        if (found) selectTemplate(found);
      }
    } catch (err) {
      setMessage({ tone: "error", text: err instanceof Error ? err.message : "Failed to load templates" });
    } finally {
      setLoading(false);
    }
  }, [workspaceId, activeKey]);

  useEffect(() => {
    void reloadTemplates();
  }, [reloadTemplates]);

  function selectTemplate(t: TemplateItem) {
    setActiveKey(t.key);
    setSubject(t.subject_template);
    setBody(t.body_template);
    setEnabled(t.enabled);
    setMessage(null);
  }

  async function saveTemplate(e: FormEvent) {
    e.preventDefault();
    if (!workspaceId || !activeKey || !canManage) return;
    setSaving(true);
    setMessage(null);
    try {
      const updated = await api<TemplateItem>(`/workspaces/${workspaceId}/notifications/templates/${activeKey}`, {
        method: "PUT",
        body: JSON.stringify({
          subject_template: subject,
          body_template: body,
          enabled,
        }),
      });
      setTemplates((current) => current.map((t) => (t.key === updated.key ? updated : t)));
      setMessage({ tone: "success", text: `Template "${TEMPLATE_INFO[updated.key]?.label || updated.key}" updated.` });
    } catch (err) {
      setMessage({ tone: "error", text: err instanceof Error ? err.message : "Error saving template" });
    } finally {
      setSaving(false);
    }
  }

  const currentInfo = TEMPLATE_INFO[activeKey] ?? {
    label: activeKey,
    description: "Custom workspace email notification template.",
    vars: [],
  };

  return (
    <section className="meeting-card notification-templates-card">
      <div className="meeting-section-title">
        <div>
          <h2><Mail size={16} style={{ display: "inline", verticalAlign: "middle", marginRight: "6px" }} /> Workspace Email Templates</h2>
          <p>Customize subjects and messages dispatched by the transactional outbox worker</p>
        </div>
        <button
          className="button button-secondary"
          type="button"
          disabled={loading || saving}
          onClick={() => void reloadTemplates()}
        >
          <RefreshCw size={14} /> Refresh
        </button>
      </div>

      {message && (
        <div className={`notice notice-${message.tone}`} role={message.tone === "error" ? "alert" : "status"}>
          <span>{message.text}</span>
          <button className="icon-button notice-close" type="button" onClick={() => setMessage(null)}>×</button>
        </div>
      )}

      <div className="notification-templates-inner">
        <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
          {templates.map((t) => {
            const info = TEMPLATE_INFO[t.key];
            const isSelected = t.key === activeKey;
            return (
              <button
                key={t.key}
                type="button"
                className={`meeting-list-item ${isSelected ? "selected" : ""}`}
                style={{ textAlign: "left", padding: "8px 10px", borderRadius: "8px" }}
                onClick={() => selectTemplate(t)}
              >
                <strong style={{ fontSize: "0.85rem" }}>{info?.label || t.key}</strong>
                <small style={{ color: t.enabled ? "var(--success, #16a34a)" : "var(--muted)" }}>
                  {t.enabled ? "Active" : "Disabled"}
                </small>
              </button>
            );
          })}
          {!templates.length && !loading && (
            <p className="meeting-empty">No workspace templates found.</p>
          )}
        </div>

        <div>
          {activeKey ? (
            <form onSubmit={(e) => void saveTemplate(e)} style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div>
                  <h3 style={{ margin: 0, fontSize: "1rem" }}>{currentInfo.label}</h3>
                  <small style={{ color: "var(--muted)" }}>{currentInfo.description}</small>
                </div>
                {canManage && (
                  <label style={{ display: "flex", alignItems: "center", gap: "6px", cursor: "pointer", fontSize: "0.85rem" }}>
                    <input
                      type="checkbox"
                      checked={enabled}
                      onChange={(e) => setEnabled(e.target.checked)}
                      style={{ width: "16px", height: "16px" }}
                    />
                    <span>{enabled ? "Enabled" : "Disabled"}</span>
                  </label>
                )}
              </div>

              {currentInfo.vars.length > 0 && (
                <div style={{ display: "flex", flexWrap: "wrap", gap: "6px", alignItems: "center" }}>
                  <span style={{ fontSize: "0.8rem", color: "var(--muted)" }}>Available variables:</span>
                  {currentInfo.vars.map((v) => (
                    <code
                      key={v}
                      style={{
                        fontSize: "0.75rem",
                        padding: "2px 6px",
                        background: "rgba(0,0,0,0.05)",
                        borderRadius: "4px",
                        cursor: canManage ? "pointer" : "default",
                      }}
                      title={canManage ? "Click to insert into subject" : undefined}
                      onClick={() => canManage && setSubject((prev) => `${prev} ${v}`)}
                    >
                      {v}
                    </code>
                  ))}
                </div>
              )}

              <label className="field">
                <span>Email Subject Template</span>
                <input
                  required
                  maxLength={300}
                  value={subject}
                  onChange={(e) => setSubject(e.target.value)}
                  readOnly={!canManage}
                />
              </label>

              <label className="field">
                <span>Email Body Template (plain text)</span>
                <textarea
                  required
                  rows={6}
                  value={body}
                  onChange={(e) => setBody(e.target.value)}
                  readOnly={!canManage}
                  style={{ fontFamily: "inherit", fontSize: "0.85rem" }}
                />
              </label>

              {canManage && (
                <div style={{ display: "flex", justifyContent: "flex-end" }}>
                  <button className="button button-primary" type="submit" disabled={saving}>
                    <Save size={15} /> {saving ? "Saving…" : "Save template"}
                  </button>
                </div>
              )}
            </form>
          ) : (
            <p className="meeting-empty">Select a template on the left to review or customize.</p>
          )}
        </div>
      </div>
    </section>
  );
}

