/** @vitest-environment jsdom */
import { describe, expect, it } from "vitest";
import {
  auditLogMatchesSearch,
  normalizeSearch,
  settingsFieldMatchesSearch,
  userMatchesSearch,
} from "./adminSearch";

describe("adminSearch", () => {
  it("normalizes search queries", () => {
    expect(normalizeSearch("  Alice  ")).toBe("alice");
  });

  it("matches settings fields by label, key, and value", () => {
    const field = {
      key: "llm_model",
      type: "string" as const,
      secret: false,
      default: "gpt-4",
      overridden: false,
      value: "gpt-4",
    };

    expect(
      settingsFieldMatchesSearch(field, "llm", "Model", "LLM"),
    ).toBe(true);
    expect(
      settingsFieldMatchesSearch(field, "gpt-4", "Model", "LLM"),
    ).toBe(true);
    expect(
      settingsFieldMatchesSearch(field, "missing", "Model", "LLM"),
    ).toBe(false);
  });

  it("matches users by name, email, and role labels", () => {
    const labels = {
      roleUser: "User",
      roleAdmin: "Admin",
      bound: "Bound",
      unbound: "Unbound",
      active: "Active",
    };
    const user = {
      id: "user-1",
      role: "admin" as const,
      display_name: "Alice",
      email: "alice@test.com",
      phone: null,
      wechat_bound: false,
      is_active: true,
      created_at: "2026-01-01T00:00:00+00:00",
    };

    expect(userMatchesSearch(user, "alice", labels)).toBe(true);
    expect(userMatchesSearch(user, "admin", labels)).toBe(true);
    expect(userMatchesSearch(user, "bob", labels)).toBe(false);
  });

  it("matches audit logs by action and actor", () => {
    const item = {
      id: "log-1",
      action: "user.update",
      actor_user_id: "admin-1",
      actor_display_name: "Admin",
      target_user_id: "user-1",
      target_display_name: "Alice",
      details: { role: { from: "user", to: "admin" } },
      created_at: "2026-01-02T12:00:00+00:00",
    };

    const translate = (key: string) =>
      key === "adminAudit.actions.user.update" ? "Update user" : key;

    expect(
      auditLogMatchesSearch(item, "admin", translate, {
        actor: "Actor",
        target: "Target",
      }),
    ).toBe(true);
    expect(
      auditLogMatchesSearch(item, "missing", translate, {
        actor: "Actor",
        target: "Target",
      }),
    ).toBe(false);
  });
});
