import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  fetchSettings,
  patchSettings,
  type SettingField,
  type SettingsGroup,
  type SettingsPayload,
} from "./api";
import UsersAdminSection from "./auth/UsersAdminSection";
import AuditLogAdminSection from "./auth/AuditLogAdminSection";
import { ChevronDownIcon } from "./icons";
import { useI18n } from "./i18n";
import SubpageTopBar from "./SubpageTopBar";

type DraftValue = string | number | boolean | null | undefined;

interface SettingsPageProps {
  isAdmin?: boolean;
}

function readDraftValue(
  field: SettingField,
  drafts: Record<string, DraftValue>,
): DraftValue {
  if (field.key in drafts) return drafts[field.key];
  if (field.secret) return "";
  return field.value ?? field.default;
}

function normalizeSearch(query: string): string {
  return query.trim().toLowerCase();
}

function fieldMatchesSearch(
  field: SettingField,
  normalizedQuery: string,
  label: string,
  groupLabel: string,
): boolean {
  if (!normalizedQuery) return true;
  return (
    label.toLowerCase().includes(normalizedQuery) ||
    groupLabel.toLowerCase().includes(normalizedQuery) ||
    field.key.toLowerCase().includes(normalizedQuery)
  );
}

interface SettingsFieldRowProps {
  field: SettingField;
  label: string;
  draft: DraftValue;
  onDraftChange: (key: string, value: DraftValue) => void;
}

function SettingsFieldRow({
  field,
  label,
  draft,
  onDraftChange,
}: SettingsFieldRowProps) {
  const { t } = useI18n();

  return (
    <label className={`settings-field${field.type === "bool" ? " settings-field--bool" : ""}`}>
      <div className="settings-field-head">
        <span className="settings-field-label">{label}</span>
        {field.overridden && draft !== null ? (
          <span className="settings-field-badge">
            {t("settings.overridden")}
          </span>
        ) : null}
      </div>

      {field.type === "bool" ? (
        <input
          type="checkbox"
          checked={
            draft === null || draft === undefined
              ? Boolean(field.default)
              : Boolean(draft)
          }
          onChange={(e) => onDraftChange(field.key, e.target.checked)}
        />
      ) : field.secret ? (
        <div className="settings-secret-wrap">
          <input
            type="password"
            value={typeof draft === "string" ? draft : ""}
            placeholder={t("settings.secretPlaceholder")}
            onChange={(e) => onDraftChange(field.key, e.target.value)}
            autoComplete="off"
          />
          {field.set && typeof draft === "string" && draft === "" ? (
            <span className="settings-secret-hint">
              {t("settings.secretHint", { masked: field.masked ?? "****" })}
            </span>
          ) : null}
        </div>
      ) : (
        <input
          type={field.type === "string" ? "text" : "number"}
          step={field.type === "float" ? "any" : "1"}
          value={draft === null || draft === undefined ? "" : String(draft)}
          onChange={(e) => {
            if (field.type === "string") {
              onDraftChange(field.key, e.target.value);
              return;
            }
            const raw = e.target.value;
            if (raw === "") {
              onDraftChange(field.key, field.default);
              return;
            }
            onDraftChange(
              field.key,
              field.type === "float"
                ? Number.parseFloat(raw)
                : Number.parseInt(raw, 10),
            );
          }}
        />
      )}
    </label>
  );
}

function fieldNeedsReset(
  field: SettingField,
  drafts: Record<string, DraftValue>,
): boolean {
  const draft = readDraftValue(field, drafts);
  if (draft === null) return field.overridden;
  if (field.secret) {
    return (
      field.overridden ||
      (typeof draft === "string" && draft.trim() !== "")
    );
  }
  const baseline = field.value ?? field.default;
  return field.overridden || draft !== baseline;
}

function canResetGroup(
  group: SettingsGroup,
  drafts: Record<string, DraftValue>,
): boolean {
  return group.fields.some((field) => fieldNeedsReset(field, drafts));
}

function buildPatchValue(
  field: SettingField,
  draft: DraftValue,
): string | number | boolean | null | undefined {
  if (field.secret) {
    if (draft === null) return null;
    if (typeof draft === "string" && draft.trim() !== "") return draft.trim();
    return undefined;
  }
  if (draft === null || draft === undefined) return null;
  return draft as string | number | boolean;
}

export default function SettingsPage({ isAdmin = false }: SettingsPageProps) {
  const { t } = useI18n();
  const [settingsTab, setSettingsTab] = useState<"system" | "users" | "audit">("system");
  const [payload, setPayload] = useState<SettingsPayload | null>(null);
  const [drafts, setDrafts] = useState<Record<string, DraftValue>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(
    () => new Set(),
  );
  const savingRef = useRef(false);
  const draftsRef = useRef(drafts);
  draftsRef.current = drafts;

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchSettings();
      setPayload(data);
      setDrafts({});
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const dirtyKeys = useMemo(() => {
    if (!payload) return new Set<string>();
    const keys = new Set<string>();
    for (const group of payload.groups) {
      for (const field of group.fields) {
        const draft = readDraftValue(field, drafts);
        if (field.secret) {
          if (typeof draft === "string" && draft.trim() !== "")
            keys.add(field.key);
          if (draft === null) keys.add(field.key);
          continue;
        }
        const baseline = field.value ?? field.default;
        if (draft !== baseline) keys.add(field.key);
      }
    }
    return keys;
  }, [payload, drafts]);

  const filteredGroups = useMemo(() => {
    if (!payload)
      return [] as Array<SettingsGroup & { visibleFields: SettingField[] }>;
    const query = normalizeSearch(searchQuery);
    return payload.groups
      .map((group) => {
        const groupLabel = t(`settings.groups.${group.id}`);
        const visibleFields = group.fields.filter((field) =>
          fieldMatchesSearch(
            field,
            query,
            t(`settings.fields.${field.key}`),
            groupLabel,
          ),
        );
        return { ...group, visibleFields };
      })
      .filter((group) => group.visibleFields.length > 0);
  }, [payload, searchQuery, t]);

  const hasSearch = normalizeSearch(searchQuery).length > 0;

  const isGroupExpanded = useCallback(
    (groupId: string) => {
      if (hasSearch) return true;
      return !collapsedGroups.has(groupId);
    },
    [collapsedGroups, hasSearch],
  );

  const toggleGroup = (groupId: string) => {
    if (hasSearch) return;
    setCollapsedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(groupId)) next.delete(groupId);
      else next.add(groupId);
      return next;
    });
  };

  const setDraft = (key: string, value: DraftValue) => {
    setDrafts((prev) => ({ ...prev, [key]: value }));
    setNotice(null);
  };

  const resetGroup = (group: SettingsGroup) => {
    setDrafts((prev) => {
      const next = { ...prev };
      for (const field of group.fields) {
        if (fieldNeedsReset(field, prev)) {
          next[field.key] = null;
        }
      }
      return next;
    });
    setNotice(null);
  };

  const persistDirtyFields = useCallback(async () => {
    const currentPayload = payload;
    if (!currentPayload || savingRef.current) return;

    const currentDrafts = draftsRef.current;
    const keysToSave = new Set<string>();
    const values: Record<string, string | number | boolean | null> = {};
    const snapshots = new Map<string, DraftValue>();

    for (const group of currentPayload.groups) {
      for (const field of group.fields) {
        const draft = readDraftValue(field, currentDrafts);
        if (field.secret) {
          const dirty =
            draft === null ||
            (typeof draft === "string" && draft.trim() !== "");
          if (!dirty) continue;
        } else {
          const baseline = field.value ?? field.default;
          if (draft === baseline) continue;
        }

        const patchValue = buildPatchValue(field, draft);
        if (patchValue === undefined) continue;

        keysToSave.add(field.key);
        snapshots.set(field.key, draft);
        values[field.key] = patchValue;
      }
    }

    if (keysToSave.size === 0) return;

    savingRef.current = true;
    setSaving(true);
    setError(null);

    try {
      const data = await patchSettings(values);
      setPayload(data);
      setDrafts((prev) => {
        const next = { ...prev };
        for (const key of keysToSave) {
          if (Object.is(next[key], snapshots.get(key))) {
            delete next[key];
          }
        }
        return next;
      });
      setNotice(t("settings.saved"));
    } catch (err) {
      setError(String(err));
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  }, [payload, t]);

  useEffect(() => {
    if (!payload || loading || dirtyKeys.size === 0) return;

    const timer = window.setTimeout(() => {
      void persistDirtyFields();
    }, 400);

    return () => window.clearTimeout(timer);
  }, [payload, loading, dirtyKeys, drafts, persistDirtyFields]);

  const showSystemSettings = !isAdmin || settingsTab === "system";
  const isAdminSectionTab = isAdmin && settingsTab !== "system";

  const navItems = isAdmin
    ? ([
        { id: "system" as const, label: t("settings.systemTab") },
        { id: "users" as const, label: t("adminUsers.title") },
        { id: "audit" as const, label: t("adminAudit.title") },
      ] satisfies Array<{ id: typeof settingsTab; label: string }>)
    : [];

  return (
    <div className={`app subpage-app${isAdmin ? " subpage-app--with-nav" : ""}`}>
      <SubpageTopBar title={t("settings.title")} />

      <div className="subpage-body">
        {isAdmin ? (
          <aside className="settings-page-nav" aria-label={t("settings.title")}>
            <div className="settings-page-nav-inner">
              <nav className="settings-page-nav-list" role="tablist">
                {navItems.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    role="tab"
                    aria-selected={settingsTab === item.id}
                    className={`settings-page-nav-item${settingsTab === item.id ? " active" : ""}`}
                    onClick={() => setSettingsTab(item.id)}
                  >
                    {item.label}
                  </button>
                ))}
              </nav>
            </div>
          </aside>
        ) : null}

        <div className="main subpage-main">
          <div className={`subpage-content settings-page${isAdmin ? " settings-page--admin" : ""}`}>
            <div
              className={`settings-page-main${isAdminSectionTab ? " settings-page-main--section-tab" : ""}`}
            >
          {showSystemSettings ? (
            <div className="settings-page-toolbar">
              <input
                type="search"
                className="settings-search settings-page-search"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder={t("settings.searchPlaceholder")}
                aria-label={t("settings.searchPlaceholder")}
              />
            </div>
          ) : null}

          <div className="settings-page-body">
            {loading ? (
              <p className="settings-page-status">{t("settings.loading")}</p>
            ) : null}
            {error ? (
              <div className="banner error settings-page-banner">{error}</div>
            ) : null}
            {notice ? (
              <div className="banner settings-page-banner">{notice}</div>
            ) : null}
            {saving ? (
              <p className="settings-page-status">{t("settings.saving")}</p>
            ) : null}

            {isAdmin && settingsTab === "users" ? (
              <div className="settings-page-section">
                <UsersAdminSection />
              </div>
            ) : null}
            {isAdmin && settingsTab === "audit" ? (
              <div className="settings-page-section">
                <AuditLogAdminSection />
              </div>
            ) : null}

            {showSystemSettings && !loading && payload && filteredGroups.length === 0 ? (
              <p className="settings-empty">{t("settings.noResults")}</p>
            ) : null}

            {showSystemSettings ? (
              <div className="settings-page-groups">
                {filteredGroups.map((group) => {
                  const expanded = isGroupExpanded(group.id);
                  const groupLabel = t(`settings.groups.${group.id}`);
                  return (
                    <section
                      key={group.id}
                      className={`settings-group ${expanded ? "expanded" : "collapsed"}`}
                    >
                      <div className="settings-group-header">
                        <button
                          type="button"
                          className="settings-group-toggle"
                          onClick={() => toggleGroup(group.id)}
                          aria-expanded={expanded}
                          aria-controls={`settings-group-${group.id}`}
                        >
                          <span className="settings-group-chevron" aria-hidden="true">
                            <ChevronDownIcon />
                          </span>
                          <span className="settings-group-title">{groupLabel}</span>
                        </button>
                        <button
                          type="button"
                          className="settings-reset-btn settings-group-reset-btn"
                          onClick={() => resetGroup(group)}
                          disabled={!canResetGroup(group, drafts)}
                          aria-label={t("settings.resetSection", { section: groupLabel })}
                        >
                          {t("settings.reset")}
                        </button>
                        <span className="settings-group-count">
                          {group.visibleFields.length}
                        </span>
                      </div>

                      {expanded ? (
                        <div
                          id={`settings-group-${group.id}`}
                          className="settings-fields"
                        >
                          {group.visibleFields.map((field) => (
                            <SettingsFieldRow
                              key={field.key}
                              field={field}
                              label={t(`settings.fields.${field.key}`)}
                              draft={readDraftValue(field, drafts)}
                              onDraftChange={setDraft}
                            />
                          ))}
                        </div>
                      ) : null}
                    </section>
                  );
                })}
              </div>
            ) : null}
          </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
