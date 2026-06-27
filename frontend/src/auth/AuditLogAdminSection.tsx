import { useCallback, useEffect, useMemo, useState } from "react";
import { fetchAdminAuditLogs, type AdminAuditLogItem } from "./api";
import {
  auditActionLabel,
  auditLogMatchesSearch,
  formatAuditDetails,
  normalizeSearch,
} from "../adminSearch";
import { useI18n } from "../i18n";

interface AuditLogAdminSectionProps {
  searchQuery?: string;
  searchMode?: boolean;
  hidden?: boolean;
  onSearchMatchChange?: (hasMatches: boolean | null) => void;
}

export default function AuditLogAdminSection({
  searchQuery = "",
  searchMode = false,
  hidden = false,
  onSearchMatchChange,
}: AuditLogAdminSectionProps) {
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

  const normalizedQuery = normalizeSearch(searchQuery);
  const hasSearch = normalizedQuery.length > 0;

  const filteredLogs = useMemo(() => {
    if (!hasSearch) return logs;
    return logs.filter((item) =>
      auditLogMatchesSearch(item, normalizedQuery, t, {
        actor: t("adminAudit.actor"),
        target: t("adminAudit.target"),
      }),
    );
  }, [logs, hasSearch, normalizedQuery, t]);

  useEffect(() => {
    if (!searchMode || !onSearchMatchChange) return;
    if (loading) {
      onSearchMatchChange(null);
      return;
    }
    onSearchMatchChange(filteredLogs.length > 0);
  }, [searchMode, loading, filteredLogs.length, onSearchMatchChange]);

  if (searchMode && hasSearch && !loading && filteredLogs.length === 0 && !error) {
    return null;
  }

  return (
    <section
      className={`audit-log-section${searchMode ? " settings-search-section" : ""}`}
      hidden={hidden}
    >
      {searchMode ? (
        <h3 className="settings-search-section-title">{t("adminAudit.title")}</h3>
      ) : (
        <div className="users-admin-head">
          <h3>{t("adminAudit.title")}</h3>
        </div>
      )}

      {loading ? <p className="settings-panel-status">{t("adminAudit.loading")}</p> : null}
      {error ? <div className="banner error settings-panel-banner">{error}</div> : null}

      {!loading && filteredLogs.length === 0 ? (
        <p className="settings-empty">{t("adminAudit.empty")}</p>
      ) : null}

      <div className="audit-log-list">
        {filteredLogs.map((item) => (
          <article key={item.id} className="audit-log-item">
            <div className="audit-log-item-main">
              <strong>{auditActionLabel(item.action, t)}</strong>
              <span className="audit-log-meta">
                {t("adminAudit.actor")}: {item.actor_display_name ?? item.actor_user_id}
                {item.target_user_id
                  ? ` · ${t("adminAudit.target")}: ${item.target_display_name ?? item.target_user_id}`
                  : ""}
              </span>
              <span className="audit-log-details">{formatAuditDetails(item.details)}</span>
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
