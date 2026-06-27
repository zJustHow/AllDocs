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

const sampleSettings = {
  groups: [
    {
      id: "llm",
      fields: [
        {
          key: "llm_model",
          type: "string" as const,
          secret: false,
          default: "gpt-4",
          overridden: false,
          value: "gpt-4",
        },
      ],
    },
  ],
};

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
    fetchSettings.mockResolvedValue(sampleSettings);
    patchSettings.mockResolvedValue(sampleSettings);
    fetchAdminUsers.mockResolvedValue(sampleUsers);
    fetchAdminAuditLogs.mockResolvedValue(sampleAuditLogs);
  });

  it("does not fetch admin data on the system tab by default", async () => {
    renderWithI18n(<SettingsPage isAdmin />);

    await screen.findByRole("heading", { name: /Management|管理/i });
    expect(fetchSettings).toHaveBeenCalledTimes(1);
    expect(fetchAdminUsers).not.toHaveBeenCalled();
    expect(fetchAdminAuditLogs).not.toHaveBeenCalled();
  });

  it("shows users and audit tabs for admins", async () => {
    const user = userEvent.setup();
    renderWithI18n(<SettingsPage isAdmin />);

    await screen.findByRole("heading", { name: /Management|管理/i });
    expect(screen.getByRole("heading", { level: 3, name: /系统配置|System/i })).toBeVisible();
    expect(screen.getByRole("tab", { name: /用户管理|Users/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /审计日志|Audit log/i })).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: /用户管理|Users/i }));
    expect(await screen.findByText("Alice")).toBeVisible();
    expect(screen.queryByText(/更新用户|Update user/i)).not.toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: /审计日志|Audit log/i }));
    expect(await screen.findByText(/更新用户|Update user/i)).toBeVisible();
    expect(screen.queryByText("Alice")).not.toBeInTheDocument();
  });

  it("searches across system settings, users, and audit logs from the top bar", async () => {
    const user = userEvent.setup();
    renderWithI18n(<SettingsPage isAdmin />);

    await screen.findByRole("heading", { name: /Management|管理/i });

    await user.type(screen.getByRole("searchbox"), "gpt-4");
    expect(await screen.findByLabelText(/模型|Model/i)).toBeInTheDocument();
    expect(screen.queryByText("Alice")).not.toBeInTheDocument();

    await user.clear(screen.getByRole("searchbox"));
    await user.type(screen.getByRole("searchbox"), "alice@test.com");
    expect(await screen.findByText("Alice")).toBeInTheDocument();
    expect(screen.queryByLabelText(/模型|Model/i)).not.toBeInTheDocument();
  });

  it("clears search when switching tabs", async () => {
    const user = userEvent.setup();
    renderWithI18n(<SettingsPage isAdmin />);

    await screen.findByRole("heading", { name: /Management|管理/i });
    await user.type(screen.getByRole("searchbox"), "alice@test.com");
    expect(await screen.findByText("Alice")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: /用户管理|Users/i }));
    expect(screen.getByRole("searchbox")).toHaveValue("");
    expect(screen.queryByLabelText(/模型|Model/i)).not.toBeInTheDocument();
  });
});
