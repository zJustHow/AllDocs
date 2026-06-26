/** @vitest-environment jsdom */
import { type ReactNode } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AuditLogAdminSection from "./AuditLogAdminSection";
import UsersAdminSection from "./UsersAdminSection";
import SettingsPage from "../SettingsPage";
import { I18nProvider } from "../i18n";

const fetchAdminUsers = vi.fn();
const patchAdminUser = vi.fn();
const fetchAdminAuditLogs = vi.fn();
const fetchSettings = vi.fn();
const patchSettings = vi.fn();

vi.mock("./api", async () => {
  const actual = await vi.importActual<typeof import("./api")>("./api");
  return {
    ...actual,
    fetchAdminUsers: (...args: Parameters<typeof fetchAdminUsers>) => fetchAdminUsers(...args),
    patchAdminUser: (...args: Parameters<typeof patchAdminUser>) => patchAdminUser(...args),
    fetchAdminAuditLogs: (...args: Parameters<typeof fetchAdminAuditLogs>) =>
      fetchAdminAuditLogs(...args),
  };
});

vi.mock("../api", async () => {
  const actual = await vi.importActual<typeof import("../api")>("../api");
  return {
    ...actual,
    fetchSettings: (...args: Parameters<typeof fetchSettings>) => fetchSettings(...args),
    patchSettings: (...args: Parameters<typeof patchSettings>) => patchSettings(...args),
  };
});

const sampleUsers = [
  {
    id: "user-1",
    role: "user" as const,
    display_name: "Alice",
    email: "alice@test.com",
    phone: null,
    wechat_bound: false,
    is_active: true,
    created_at: "2026-01-01T00:00:00+00:00",
  },
];

const sampleAuditLogs = [
  {
    id: "log-1",
    action: "user.update",
    actor_user_id: "admin-1",
    actor_display_name: "Admin",
    target_user_id: "user-1",
    target_display_name: "Alice",
    details: { role: { from: "user", to: "admin" } },
    created_at: "2026-01-02T12:00:00+00:00",
  },
];

const emptySettings = { groups: [] };

function renderWithI18n(node: ReactNode) {
  return render(<I18nProvider>{node}</I18nProvider>);
}

describe("UsersAdminSection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    fetchAdminUsers.mockResolvedValue(sampleUsers);
    patchAdminUser.mockImplementation(async (_id, patch) => ({ ...sampleUsers[0], ...patch }));
  });

  it("loads and renders users", async () => {
    renderWithI18n(<UsersAdminSection />);
    expect(await screen.findByText("Alice")).toBeInTheDocument();
    expect(fetchAdminUsers).toHaveBeenCalledTimes(1);
  });

  it("patches user role", async () => {
    const user = userEvent.setup();
    renderWithI18n(<UsersAdminSection />);
    await screen.findByText("Alice");

    await user.selectOptions(screen.getByRole("combobox"), "admin");

    await waitFor(() => {
      expect(patchAdminUser).toHaveBeenCalledWith("user-1", { role: "admin" });
    });
  });
});

describe("AuditLogAdminSection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    fetchAdminAuditLogs.mockResolvedValue(sampleAuditLogs);
  });

  it("loads and renders audit entries", async () => {
    renderWithI18n(<AuditLogAdminSection />);
    expect(await screen.findByText(/更新用户|Update user/i)).toBeInTheDocument();
    expect(screen.getByText(/Admin/)).toBeInTheDocument();
    expect(screen.getByText(/role: user → admin/i)).toBeInTheDocument();
  });
});

describe("SettingsPage admin tabs", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    fetchSettings.mockResolvedValue(emptySettings);
    fetchAdminUsers.mockResolvedValue(sampleUsers);
    fetchAdminAuditLogs.mockResolvedValue(sampleAuditLogs);
  });

  it("shows users and audit tabs for admins", async () => {
    const user = userEvent.setup();
    renderWithI18n(<SettingsPage isAdmin />);

    await screen.findByRole("heading", { name: /Management|管理/i });
    expect(screen.getByRole("tab", { name: /用户管理|Users/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /审计日志|Audit log/i })).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: /用户管理|Users/i }));
    expect(await screen.findByText("Alice")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: /审计日志|Audit log/i }));
    expect(await screen.findByText(/更新用户|Update user/i)).toBeInTheDocument();
  });
});
