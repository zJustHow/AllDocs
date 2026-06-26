import { useCallback, useEffect, useState } from "react";
import { fetchAdminAuditLogs, type AdminAuditLogItem } from "./api";
import { useI18n } from "../i18n";

function formatDetails(details: Record<string, unknown> | null): string {
  if (!details) return "—";
  return Object.entries(details)
    .map(([key, value]) => {
      if (value && typeof value === "object" && "from" in value && "to" in value) {
        const change = value as { from: unknown; to: unknown };
        return `${key}: ${String(change.from)} → ${String(change.to)}`;
      }
      return `${key}: ${JSON.stringify(value)}`;
    })
    .join(" · ");
}

function actionLabel(action: string, translate: (key: string) => string): string {
  const key = `adminAudit.actions.${action.split(".").join(".")}`;
  const label = translate(key);
  return label === key ? action : label;
}

export default function AuditLogAdminSection() {
  const { t } = useI18n();
  const [logs, setLogs] = useState<AdminAuditLogItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadLogs = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setLogs(await fetchAdminAuditLogs());
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadLogs();
  }, [loadLogs]);

  return (
    <section className="audit-log-section">
      <div className="users-admin-head">
        <h3>{t("adminAudit.title")}</h3>
      </div>

      {loading ? <p className="settings-panel-status">{t("adminAudit.loading")}</p> : null}
      {error ? <div className="banner error settings-panel-banner">{error}</div> : null}

      {!loading && logs.length === 0 ? (
        <p className="settings-empty">{t("adminAudit.empty")}</p>
      ) : null}

      <div className="audit-log-list">
        {logs.map((item) => (
          <article key={item.id} className="audit-log-item">
            <div className="audit-log-item-main">
              <strong>{actionLabel(item.action, t)}</strong>
              <span className="audit-log-meta">
                {t("adminAudit.actor")}: {item.actor_display_name ?? item.actor_user_id}
                {item.target_user_id
                  ? ` · ${t("adminAudit.target")}: ${item.target_display_name ?? item.target_user_id}`
                  : ""}
              </span>
              <span className="audit-log-details">{formatDetails(item.details)}</span>
            </div>
            <time className="audit-log-time" dateTime={item.created_at}>
              {new Date(item.created_at).toLocaleString()}
            </time>
          </article>
        ))}
      </div>
    </section>
  );
}
