/** @vitest-environment jsdom */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ProfilePage from "./ProfilePage";
import { I18nProvider } from "./i18n";
import type { AuthUser } from "./auth/types";

const refreshUser = vi.fn();
const unbindIdentity = vi.fn();
const onLogout = vi.fn();

let mockUser: AuthUser | null = {
  id: "user-1",
  role: "user",
  display_name: "Test User",
  email: "user@test.com",
  phone: "+8613800138000",
  wechat_bound: false,
};

vi.mock("./auth/AuthContext", () => ({
  useAuth: () => ({
    user: mockUser,
    refreshUser,
  }),
}));

vi.mock("./auth/api", async () => {
  const actual = await vi.importActual<typeof import("./auth/api")>("./auth/api");
  return {
    ...actual,
    unbindIdentity: (...args: Parameters<typeof unbindIdentity>) => unbindIdentity(...args),
    wechatBindAuthorizeUrl: () => "/api/v1/auth/wechat/bind/authorize",
  };
});

function renderPage() {
  return render(
    <I18nProvider>
      <ProfilePage onLogout={onLogout} />
    </I18nProvider>,
  );
}

describe("ProfilePage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUser = {
      id: "user-1",
      role: "user",
      display_name: "Test User",
      email: "user@test.com",
      phone: "+8613800138000",
      wechat_bound: false,
    };
    unbindIdentity.mockResolvedValue({
      ...mockUser,
      email: null,
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);
  });

  it("shows profile title and bound identities", async () => {
    renderPage();
    expect(await screen.findByRole("heading", { name: /账号|Account/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Test User/i, level: 2 })).toBeInTheDocument();
    expect(screen.getAllByText("user@test.com").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("****8000")).toBeInTheDocument();
  });

  it("unbinds email after confirmation", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getAllByRole("button", { name: /解绑|Unlink/i })[0]);

    await waitFor(() => {
      expect(unbindIdentity).toHaveBeenCalledWith("email");
      expect(refreshUser).toHaveBeenCalled();
    });
    expect(await screen.findByText(/已解绑|Unlinked/i)).toBeInTheDocument();
  });

  it("logs out from the footer", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("button", { name: /退出|Sign out/i }));
    expect(onLogout).toHaveBeenCalledTimes(1);
  });

  it("shows loading state when user is not yet available", async () => {
    mockUser = null;
    renderPage();

    expect(await screen.findByText(/Loading settings|加载设置/i)).toBeInTheDocument();
  });

  it("shows admin role badge and phone-only subtitle", async () => {
    mockUser = {
      id: "admin-1",
      role: "admin",
      display_name: "Admin User",
      email: null,
      phone: "+8613800138000",
      wechat_bound: true,
    };
    renderPage();

    expect(await screen.findByRole("heading", { name: /Admin User/i, level: 2 })).toBeInTheDocument();
    expect(document.querySelector(".profile-role-badge")?.textContent).toMatch(/Admin|管理员/);
    expect(document.querySelector(".profile-subtitle")?.textContent).toBe("****8000");
  });

  it("keeps short phone numbers visible without masking", async () => {
    mockUser = {
      id: "user-2",
      role: "user",
      display_name: "Phone User",
      email: null,
      phone: "123",
      wechat_bound: false,
    };
    renderPage();

    expect(await screen.findByRole("heading", { name: /Phone User/i, level: 2 })).toBeInTheDocument();
    expect(document.querySelector(".profile-subtitle")?.textContent).toBe("123");
  });
});
