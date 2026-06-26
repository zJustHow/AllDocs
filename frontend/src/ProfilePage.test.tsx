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
});
