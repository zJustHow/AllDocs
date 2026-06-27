import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  fetchSettings,
  patchSettings,
  type SettingField,
  type SettingsGroup,
  type SettingsPayload,
} from "./api";
import {
  normalizeSearch,
  settingsFieldMatchesSearch,
} from "./adminSearch";
import { ChevronDownIcon } from "./icons";
import { useDebouncedValue } from "./hooks/useDebouncedValue";
import { useI18n } from "./i18n";
import SubpageTopBar from "./SubpageTopBar";

const SEARCH_DEBOUNCE_MS = 200;

const UsersAdminSection = lazy(() => import("./auth/UsersAdminSection"));
const AuditLogAdminSection = lazy(() => import("./auth/AuditLogAdminSection"));

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

interface SettingsGroupsProps {
  groups: Array<SettingsGroup & { visibleFields: SettingField[] }>;
  drafts: Record<string, DraftValue>;
  isGroupExpanded: (groupId: string) => boolean;
  toggleGroup: (groupId: string) => void;
  resetGroup: (group: SettingsGroup) => void;
  setDraft: (key: string, value: DraftValue) => void;
  searchMode?: boolean;
  showSectionTitle?: boolean;
}

function SettingsGroups({
  groups,
  drafts,
  isGroupExpanded,
  toggleGroup,
  resetGroup,
  setDraft,
  searchMode = false,
  showSectionTitle = false,
}: SettingsGroupsProps) {
  const { t } = useI18n();

  if (groups.length === 0) return null;

  const content = (
    <div className="settings-page-groups">
      {groups.map((group) => {
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
              <div id={`settings-group-${group.id}`} className="settings-fields">
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
  );

  if (!searchMode) {
    if (!showSectionTitle) return content;
    return (
      <section className="users-admin-section">
        <div className="users-admin-head">
          <h3>{t("settings.systemTab")}</h3>
        </div>
        {content}
      </section>
    );
  }

  return (
    <section className="settings-search-section">
      <h3 className="settings-search-section-title">{t("settings.systemTab")}</h3>
      {content}
    </section>
  );
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
  const debouncedSearchQuery = useDebouncedValue(searchQuery, SEARCH_DEBOUNCE_MS);
  const [userSearchMatch, setUserSearchMatch] = useState<boolean | null>(null);
  const [auditSearchMatch, setAuditSearchMatch] = useState<boolean | null>(null);
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(
    () => new Set(),
  );
  const savingRef = useRef(false);
  const draftsRef = useRef(drafts);
  const subpageMainRef = useRef<HTMLDivElement>(null);
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
    const query = normalizeSearch(debouncedSearchQuery);
    return payload.groups
      .map((group) => {
        const groupLabel = t(`settings.groups.${group.id}`);
        const visibleFields = group.fields.filter((field) =>
          settingsFieldMatchesSearch(
            field,
            query,
            t(`settings.fields.${field.key}`),
            groupLabel,
          ),
        );
        return { ...group, visibleFields };
      })
      .filter((group) => group.visibleFields.length > 0);
  }, [payload, debouncedSearchQuery, t]);

  const hasSearch = normalizeSearch(debouncedSearchQuery).length > 0;
  const showUnifiedSearch = isAdmin && hasSearch;
  const showUsersSection = isAdmin && (settingsTab === "users" || showUnifiedSearch);
  const showAuditSection = isAdmin && (settingsTab === "audit" || showUnifiedSearch);

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

  const showSystemSettings = !isAdmin || settingsTab === "system" || showUnifiedSearch;

  const selectSettingsTab = (tab: typeof settingsTab) => {
    setSearchQuery("");
    setSettingsTab(tab);
  };

  useEffect(() => {
    subpageMainRef.current?.scrollTo({ top: 0 });
  }, [settingsTab, showUnifiedSearch]);

  useEffect(() => {
    if (!showUnifiedSearch) {
      setUserSearchMatch(null);
      setAuditSearchMatch(null);
    }
  }, [showUnifiedSearch]);

  const unifiedSearchPending =
    showUnifiedSearch && (loading || userSearchMatch === null || auditSearchMatch === null);
  const unifiedSearchEmpty =
    showUnifiedSearch &&
    !unifiedSearchPending &&
    filteredGroups.length === 0 &&
    userSearchMatch === false &&
    auditSearchMatch === false;

  const showSystemEmpty =
    showSystemSettings &&
    !loading &&
    payload &&
    filteredGroups.length === 0 &&
    !showUnifiedSearch;

  const navItems = isAdmin
    ? ([
        { id: "system" as const, label: t("settings.systemTab") },
        { id: "users" as const, label: t("adminUsers.title") },
        { id: "audit" as const, label: t("adminAudit.title") },
      ] satisfies Array<{ id: typeof settingsTab; label: string }>)
    : [];

  return (
    <div className={`app subpage-app${isAdmin ? " subpage-app--with-nav" : ""}`}>
      <SubpageTopBar title={t("settings.title")}>
        <input
          type="search"
          className="settings-search subpage-top-bar-search"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder={t(isAdmin ? "settings.searchPlaceholderAdmin" : "settings.searchPlaceholder")}
          aria-label={t(isAdmin ? "settings.searchPlaceholderAdmin" : "settings.searchPlaceholder")}
        />
      </SubpageTopBar>

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
                    aria-selected={!showUnifiedSearch && settingsTab === item.id}
                    className={`settings-page-nav-item${!showUnifiedSearch && settingsTab === item.id ? " active" : ""}`}
                    onClick={() => selectSettingsTab(item.id)}
                  >
                    {item.label}
                  </button>
                ))}
              </nav>
            </div>
          </aside>
        ) : null}

        <div className="main subpage-main" ref={isAdmin ? subpageMainRef : undefined}>
          <div className={`subpage-content settings-page${isAdmin ? " settings-page--admin" : ""}`}>
            <div className="settings-page-main">
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

                {unifiedSearchEmpty ? (
                  <p className="settings-empty">{t("settings.noResults")}</p>
                ) : null}

                {showSystemEmpty ? (
                  <p className="settings-empty">{t("settings.noResults")}</p>
                ) : null}

                {showSystemSettings && !loading && payload ? (
                  <SettingsGroups
                    groups={filteredGroups}
                    drafts={drafts}
                    isGroupExpanded={isGroupExpanded}
                    toggleGroup={toggleGroup}
                    resetGroup={resetGroup}
                    setDraft={setDraft}
                    searchMode={showUnifiedSearch}
                    showSectionTitle={isAdmin && !showUnifiedSearch}
                  />
                ) : null}

                {showUsersSection || showAuditSection ? (
                  <Suspense fallback={null}>
                    {showUsersSection ? (
                      <UsersAdminSection
                        searchQuery={debouncedSearchQuery}
                        searchMode={showUnifiedSearch}
                        onSearchMatchChange={
                          showUnifiedSearch ? setUserSearchMatch : undefined
                        }
                      />
                    ) : null}
                    {showAuditSection ? (
                      <AuditLogAdminSection
                        searchQuery={debouncedSearchQuery}
                        searchMode={showUnifiedSearch}
                        onSearchMatchChange={
                          showUnifiedSearch ? setAuditSearchMatch : undefined
                        }
                      />
                    ) : null}
                  </Suspense>
                ) : null}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
