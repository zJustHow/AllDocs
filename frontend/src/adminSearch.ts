import type { AdminAuditLogItem, AdminUserItem } from "./auth/api";
import type { SettingField } from "./api";

export function normalizeSearch(query: string): string {
  return query.trim().toLowerCase();
}

export function textMatchesSearch(text: string, normalizedQuery: string): boolean {
  if (!normalizedQuery) return true;
  return text.toLowerCase().includes(normalizedQuery);
}

export function settingsFieldMatchesSearch(
  field: SettingField,
  normalizedQuery: string,
  label: string,
  groupLabel: string,
): boolean {
  if (!normalizedQuery) return true;
  const parts = [
    label,
    groupLabel,
    field.key,
    field.value === null || field.value === undefined ? "" : String(field.value),
    field.default === null || field.default === undefined ? "" : String(field.default),
    field.masked ?? "",
  ];
  return parts.some((part) => part && textMatchesSearch(part, normalizedQuery));
}

export function auditActionLabel(
  action: string,
  translate: (key: string) => string,
): string {
  const key = `adminAudit.actions.${action.split(".").join(".")}`;
  const label = translate(key);
  return label === key ? action : label;
}

export function formatAuditDetails(details: Record<string, unknown> | null): string {
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

export function userMatchesSearch(
  user: AdminUserItem,
  normalizedQuery: string,
  labels: {
    roleUser: string;
    roleAdmin: string;
    bound: string;
    unbound: string;
    active: string;
  },
): boolean {
  if (!normalizedQuery) return true;
  const parts = [
    user.id,
    user.display_name,
    user.email,
    user.phone,
    user.role,
    user.role === "admin" ? labels.roleAdmin : labels.roleUser,
    user.is_active ? labels.active : "",
    user.wechat_bound ? labels.bound : labels.unbound,
  ];
  return parts.some((part) => part && textMatchesSearch(String(part), normalizedQuery));
}

export function auditLogMatchesSearch(
  item: AdminAuditLogItem,
  normalizedQuery: string,
  translate: (key: string) => string,
  labels: { actor: string; target: string },
): boolean {
  if (!normalizedQuery) return true;
  const parts = [
    item.action,
    auditActionLabel(item.action, translate),
    item.actor_user_id,
    item.actor_display_name,
    item.target_user_id,
    item.target_display_name,
    formatAuditDetails(item.details),
    labels.actor,
    labels.target,
    new Date(item.created_at).toLocaleString(),
  ];
  return parts.some((part) => part && textMatchesSearch(String(part), normalizedQuery));
}
