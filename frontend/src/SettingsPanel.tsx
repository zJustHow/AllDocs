import { useCallback, useEffect, useMemo, useState } from "react";
import {
  fetchSettings,
  patchSettings,
  type SettingField,
  type SettingsGroup,
  type SettingsPayload,
} from "./api";
import { ChevronDownIcon, CloseIcon } from "./icons";
import { useI18n } from "./i18n";

type DraftValue = string | number | boolean | null | undefined;

interface SettingsPanelProps {
  open: boolean;
  onClose: () => void;
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
  onReset: (field: SettingField) => void;
}

function SettingsFieldRow({
  field,
  label,
  draft,
  onDraftChange,
  onReset,
}: SettingsFieldRowProps) {
  const { t } = useI18n();
  const resetToDefault = draft === null;

  return (
    <label className="settings-field">
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

      <div className="settings-field-actions">
        <button
          type="button"
          className="settings-reset-btn"
          onClick={() => onReset(field)}
          disabled={resetToDefault && !field.overridden}
        >
          {t("settings.reset")}
        </button>
      </div>
    </label>
  );
}

export default function SettingsPanel({ open, onClose }: SettingsPanelProps) {
  const { t } = useI18n();
  const [payload, setPayload] = useState<SettingsPayload | null>(null);
  const [drafts, setDrafts] = useState<Record<string, DraftValue>>({});
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(
    () => new Set(),
  );

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
    if (!open) return;
    setNotice(null);
    setSearchQuery("");
    setCollapsedGroups(new Set());
    void load();
  }, [open, load]);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

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

  const resetField = (field: SettingField) => {
    setDraft(field.key, null);
  };

  const handleSave = async () => {
    if (!payload || dirtyKeys.size === 0) return;
    setSaving(true);
    setError(null);
    setNotice(null);
    const values: Record<string, string | number | boolean | null> = {};
    for (const group of payload.groups) {
      for (const field of group.fields) {
        if (!dirtyKeys.has(field.key)) continue;
        const draft = readDraftValue(field, drafts);
        if (field.secret) {
          if (draft === null) {
            values[field.key] = null;
          } else if (typeof draft === "string" && draft.trim() !== "") {
            values[field.key] = draft.trim();
          }
          continue;
        }
        if (draft === null || draft === undefined) {
          values[field.key] = null;
          continue;
        }
        values[field.key] = draft as string | number | boolean;
      }
    }

    try {
      const data = await patchSettings(values);
      setPayload(data);
      setDrafts({});
      setNotice(t("settings.saved"));
    } catch (err) {
      setError(String(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <aside
      className={`settings-panel ${open ? "open" : "collapsed"}`}
      aria-hidden={!open}
    >
      <div
        className="settings-panel-inner"
        role="dialog"
        aria-modal={open}
        aria-labelledby="settings-panel-title"
        aria-hidden={!open}
      >
        <header className="settings-panel-header">
          <div className="settings-panel-header-top">
            <h2 id="settings-panel-title">{t("settings.title")}</h2>
            <button
              type="button"
              className="icon-btn settings-panel-close"
              onClick={onClose}
              aria-label={t("dialog.close")}
            >
              <CloseIcon />
            </button>
          </div>
          <input
            type="search"
            className="settings-search"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder={t("settings.searchPlaceholder")}
            aria-label={t("settings.searchPlaceholder")}
          />
        </header>

        {loading ? (
          <p className="settings-panel-status">{t("settings.loading")}</p>
        ) : null}
        {error ? (
          <div className="banner error settings-panel-banner">{error}</div>
        ) : null}
        {notice ? (
          <div className="banner settings-panel-banner">{notice}</div>
        ) : null}

        <div className="settings-panel-body">
          {!loading && payload && filteredGroups.length === 0 ? (
            <p className="settings-empty">{t("settings.noResults")}</p>
          ) : null}

          {filteredGroups.map((group) => {
            const expanded = isGroupExpanded(group.id);
            const groupLabel = t(`settings.groups.${group.id}`);
            return (
              <section
                key={group.id}
                className={`settings-group ${expanded ? "expanded" : "collapsed"}`}
              >
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
                  <span className="settings-group-count">
                    {group.visibleFields.length}
                  </span>
                </button>

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
                        onReset={resetField}
                      />
                    ))}
                  </div>
                ) : null}
              </section>
            );
          })}
        </div>

        <footer className="settings-panel-footer">
          <button
            type="button"
            className="confirm-dialog-btn"
            onClick={onClose}
          >
            {t("dialog.cancel")}
          </button>
          <button
            type="button"
            className="confirm-dialog-btn primary"
            onClick={() => void handleSave()}
            disabled={saving || dirtyKeys.size === 0}
          >
            {saving ? t("settings.saving") : t("settings.save")}
          </button>
        </footer>
      </div>
    </aside>
  );
}
