import { useCallback, useEffect, useState } from "react";
import { fetchAdminUsers, patchAdminUser, type AdminUserItem } from "./api";
import { useI18n } from "../i18n";

export default function UsersAdminSection() {
  const { t } = useI18n();
  const [users, setUsers] = useState<AdminUserItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [savingId, setSavingId] = useState<string | null>(null);

  const loadUsers = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setUsers(await fetchAdminUsers());
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadUsers();
  }, [loadUsers]);

  const handlePatch = async (
    userId: string,
    patch: Partial<Pick<AdminUserItem, "role" | "is_active" | "display_name">>,
  ) => {
    setSavingId(userId);
    setError(null);
    try {
      const updated = await patchAdminUser(userId, patch);
      setUsers((prev) => prev.map((item) => (item.id === userId ? updated : item)));
    } catch (err) {
      setError(String(err));
    } finally {
      setSavingId(null);
    }
  };

  return (
    <section className="users-admin-section">
      <div className="users-admin-head">
        <h3>{t("adminUsers.title")}</h3>
      </div>

      {loading ? <p className="settings-panel-status">{t("adminUsers.loading")}</p> : null}
      {error ? <div className="banner error settings-panel-banner">{error}</div> : null}

      {!loading && users.length === 0 ? (
        <p className="settings-empty">{t("adminUsers.empty")}</p>
      ) : null}

      <div className="users-admin-list">
        {users.map((item) => (
          <article key={item.id} className="users-admin-item">
            <div className="users-admin-item-main">
              <strong>{item.display_name ?? item.email ?? item.phone ?? item.id}</strong>
              <span className="users-admin-meta">
                {item.email ?? "—"} · {item.phone ?? "—"} ·{" "}
                {item.wechat_bound ? t("account.bound") : t("account.unbound")}
              </span>
            </div>
            <div className="users-admin-actions">
              <label className="users-admin-field">
                <select
                  aria-label={t("adminUsers.role")}
                  value={item.role}
                  disabled={savingId === item.id}
                  onChange={(e) =>
                    void handlePatch(item.id, {
                      role: e.target.value as AdminUserItem["role"],
                    })
                  }
                >
                  <option value="user">{t("account.roleUser")}</option>
                  <option value="admin">{t("account.roleAdmin")}</option>
                </select>
              </label>
              <label className="users-admin-toggle">
                <input
                  type="checkbox"
                  checked={item.is_active}
                  disabled={savingId === item.id}
                  onChange={(e) => void handlePatch(item.id, { is_active: e.target.checked })}
                />
                <span>{t("adminUsers.active")}</span>
              </label>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
