/** @vitest-environment jsdom */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import LoginPage from "./LoginPage";
import { I18nProvider } from "../i18n";

const login = vi.fn();
const register = vi.fn();
const loginWithPhone = vi.fn();
const sendPhoneOtp = vi.fn();
const sendRegisterEmailOtp = vi.fn();

vi.mock("./AuthContext", () => ({
  useAuth: () => ({
    login,
    register,
    loginWithPhone,
  }),
}));

vi.mock("./api", async () => {
  const actual = await vi.importActual<typeof import("./api")>("./api");
  return {
    ...actual,
    sendPhoneOtp: (...args: unknown[]) => sendPhoneOtp(...args),
    sendRegisterEmailOtp: (...args: unknown[]) => sendRegisterEmailOtp(...args),
    wechatAuthorizeUrl: () => "/api/v1/auth/wechat/authorize",
  };
});

function renderPage() {
  return render(
    <I18nProvider>
      <LoginPage />
    </I18nProvider>,
  );
}

describe("LoginPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    login.mockResolvedValue(undefined);
    register.mockResolvedValue(undefined);
    loginWithPhone.mockResolvedValue(undefined);
    sendPhoneOtp.mockResolvedValue(undefined);
    sendRegisterEmailOtp.mockResolvedValue(undefined);
  });

  it("logs in with email and password", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.type(screen.getByLabelText(/^Email$/i), "user@test.com");
    await user.type(screen.getByLabelText(/^Password$/i), "password123");
    await user.click(screen.getByRole("button", { name: /^Sign in$/i }));

    await waitFor(() => {
      expect(login).toHaveBeenCalledWith("user@test.com", "password123");
    });
  });

  it("registers with email OTP", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("button", { name: /^Register$/i }));
    await user.type(screen.getByLabelText(/^Email$/i), "new@test.com");
    await user.click(screen.getByRole("button", { name: /^Send code$/i }));
    await user.type(screen.getByLabelText(/^Verification code/i), "654321");
    await user.type(screen.getAllByLabelText(/^Password$/i)[0], "password123");
    await user.click(screen.getByRole("button", { name: /^Create account$/i }));

    await waitFor(() => {
      expect(sendRegisterEmailOtp).toHaveBeenCalledWith("new@test.com");
      expect(register).toHaveBeenCalledWith(
        "new@test.com",
        "654321",
        "password123",
        undefined,
      );
    });
  });

  it("logs in with phone OTP", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("tab", { name: /^Phone$/i }));
    await user.type(screen.getByLabelText(/^Phone number$/i), "+8613800138000");
    await user.click(screen.getByRole("button", { name: /^Send code$/i }));
    await user.type(screen.getByLabelText(/^Verification code/i), "112233");
    await user.click(screen.getByRole("button", { name: /^Continue$/i }));

    await waitFor(() => {
      expect(sendPhoneOtp).toHaveBeenCalledWith("+8613800138000");
      expect(loginWithPhone).toHaveBeenCalledWith("+8613800138000", "112233");
    });
  });

  it("shows submit errors", async () => {
    login.mockRejectedValue(new Error("Invalid credentials"));
    const user = userEvent.setup();
    renderPage();

    await user.type(screen.getByLabelText(/^Email$/i), "user@test.com");
    await user.type(screen.getByLabelText(/^Password$/i), "bad-password");
    await user.click(screen.getByRole("button", { name: /^Sign in$/i }));

    expect(await screen.findByText(/Invalid credentials/i)).toBeInTheDocument();
  });

  it("links to WeChat authorize", () => {
    renderPage();
    expect(screen.getByRole("link", { name: /微信|WeChat/i })).toHaveAttribute(
      "href",
      "/api/v1/auth/wechat/authorize",
    );
  });
});
