/** @vitest-environment jsdom */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AccountContent from "./AccountContent";
import { I18nProvider } from "../i18n";
import type { AuthUser } from "./types";

const refreshUser = vi.fn();
const bindEmail = vi.fn();
const bindPhone = vi.fn();
const sendBindPhoneOtp = vi.fn();
const unbindIdentity = vi.fn();

let mockUser: AuthUser | null = {
  id: "user-1",
  role: "user",
  display_name: "Test User",
  email: null,
  phone: null,
  wechat_bound: false,
};

vi.mock("./AuthContext", () => ({
  useAuth: () => ({
    user: mockUser,
    refreshUser,
  }),
}));

vi.mock("./api", async () => {
  const actual = await vi.importActual<typeof import("./api")>("./api");
  return {
    ...actual,
    bindEmail: (...args: unknown[]) => bindEmail(...args),
    bindPhone: (...args: unknown[]) => bindPhone(...args),
    sendBindPhoneOtp: (...args: unknown[]) => sendBindPhoneOtp(...args),
    unbindIdentity: (...args: unknown[]) => unbindIdentity(...args),
    wechatBindAuthorizeUrl: () => "/api/v1/auth/wechat/bind/authorize?token=abc",
  };
});

function renderContent() {
  return render(
    <I18nProvider>
      <AccountContent />
    </I18nProvider>,
  );
}

describe("AccountContent", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUser = {
      id: "user-1",
      role: "user",
      display_name: "Test User",
      email: null,
      phone: null,
      wechat_bound: false,
    };
    bindEmail.mockResolvedValue(mockUser);
    bindPhone.mockResolvedValue(mockUser);
    sendBindPhoneOtp.mockResolvedValue(undefined);
    unbindIdentity.mockResolvedValue(mockUser);
    refreshUser.mockResolvedValue(undefined);
    vi.spyOn(window, "confirm").mockReturnValue(true);
  });

  it("renders nothing without a user", () => {
    mockUser = null;
    const { container } = renderContent();
    expect(container).toBeEmptyDOMElement();
  });

  it("binds email and phone identities", async () => {
    const user = userEvent.setup();
    renderContent();

    await user.type(screen.getByLabelText(/^Email$/i), "user@test.com");
    await user.type(screen.getByLabelText(/^Password$/i), "password123");
    await user.click(screen.getAllByRole("button", { name: /^Link$/i })[0]);

    await waitFor(() => {
      expect(bindEmail).toHaveBeenCalledWith("user@test.com", "password123");
      expect(refreshUser).toHaveBeenCalled();
    });

    await user.type(screen.getByLabelText(/^Phone number$/i), "+8613800138000");
    await user.click(screen.getByRole("button", { name: /^Send code$/i }));
    await user.type(screen.getByLabelText(/^Verification code/i), "123456");
    await user.click(screen.getAllByRole("button", { name: /^Link$/i })[1]);

    await waitFor(() => {
      expect(sendBindPhoneOtp).toHaveBeenCalledWith("+8613800138000");
      expect(bindPhone).toHaveBeenCalledWith("+8613800138000", "123456");
    });
  });

  it("shows WeChat bind link when WeChat is not bound", () => {
    renderContent();
    expect(screen.getByRole("link", { name: /Link with WeChat QR/i })).toHaveAttribute(
      "href",
      "/api/v1/auth/wechat/bind/authorize?token=abc",
    );
  });

  it("unbinds identities when multiple methods are bound", async () => {
    mockUser = {
      id: "user-1",
      role: "user",
      display_name: "Test User",
      email: "user@test.com",
      phone: "+8613800138000",
      wechat_bound: true,
    };

    const user = userEvent.setup();
    renderContent();

    await user.click(screen.getAllByRole("button", { name: /^Unlink$/i })[0]);
    await waitFor(() => {
      expect(unbindIdentity).toHaveBeenCalledWith("email");
      expect(refreshUser).toHaveBeenCalled();
    });
  });

  it("skips unbind when confirmation is cancelled", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    mockUser = {
      id: "user-1",
      role: "user",
      display_name: "Test User",
      email: "user@test.com",
      phone: "+8613800138000",
      wechat_bound: false,
    };

    const user = userEvent.setup();
    renderContent();
    await user.click(screen.getAllByRole("button", { name: /^Unlink$/i })[0]);
    expect(unbindIdentity).not.toHaveBeenCalled();
  });
});
