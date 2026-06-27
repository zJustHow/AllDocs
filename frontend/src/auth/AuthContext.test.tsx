/** @vitest-environment jsdom */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AuthProvider, useAuth } from "./AuthContext";
import { I18nProvider } from "../i18n";
import type { AuthUser, TokenPair } from "./types";

const sampleUser: AuthUser = {
  id: "user-1",
  role: "admin",
  display_name: "Admin User",
  email: "admin@test.com",
  phone: null,
  wechat_bound: false,
};

const sampleTokens: TokenPair = {
  access_token: "access-token",
  refresh_token: "refresh-token",
  token_type: "bearer",
};

const fetchCurrentUser = vi.fn();
const loginWithEmail = vi.fn();
const registerWithEmailOtp = vi.fn();
const verifyPhoneOtp = vi.fn();
const applyTokenPair = vi.fn();
const refreshAuthTokens = vi.fn();
const logoutRemote = vi.fn();
const hasStoredSession = vi.fn();
const clearTokens = vi.fn();

vi.mock("./api", () => ({
  fetchCurrentUser: (...args: unknown[]) => fetchCurrentUser(...args),
  loginWithEmail: (...args: unknown[]) => loginWithEmail(...args),
  registerWithEmailOtp: (...args: unknown[]) => registerWithEmailOtp(...args),
  verifyPhoneOtp: (...args: unknown[]) => verifyPhoneOtp(...args),
  applyTokenPair: (...args: unknown[]) => applyTokenPair(...args),
  refreshAuthTokens: (...args: unknown[]) => refreshAuthTokens(...args),
  logoutRemote: (...args: unknown[]) => logoutRemote(...args),
}));

vi.mock("./session", () => ({
  hasStoredSession: (...args: unknown[]) => hasStoredSession(...args),
}));

vi.mock("./tokenStore", () => ({
  clearTokens: (...args: unknown[]) => clearTokens(...args),
}));

function AuthProbe() {
  const auth = useAuth();
  return (
    <div>
      <span data-testid="loading">{String(auth.loading)}</span>
      <span data-testid="user">{auth.user?.email ?? "none"}</span>
      <span data-testid="admin">{String(auth.isAdmin)}</span>
      <button type="button" onClick={() => void auth.login("user@test.com", "password123")}>
        login
      </button>
      <button
        type="button"
        onClick={() => void auth.register("user@test.com", "123456", "password123", "Test")}
      >
        register
      </button>
      <button type="button" onClick={() => void auth.loginWithPhone("+8613800138000", "123456")}>
        phone-login
      </button>
      <button type="button" onClick={() => void auth.completeOAuthLogin(sampleTokens)}>
        oauth
      </button>
      <button type="button" onClick={() => void auth.refreshUser()}>
        refresh
      </button>
      <button type="button" onClick={() => void auth.logout()}>
        logout
      </button>
    </div>
  );
}

function renderAuth() {
  return render(
    <I18nProvider>
      <AuthProvider>
        <AuthProbe />
      </AuthProvider>
    </I18nProvider>,
  );
}

describe("AuthContext", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    hasStoredSession.mockReturnValue(false);
    fetchCurrentUser.mockResolvedValue(sampleUser);
    loginWithEmail.mockResolvedValue(sampleTokens);
    registerWithEmailOtp.mockResolvedValue(sampleTokens);
    verifyPhoneOtp.mockResolvedValue(sampleTokens);
    applyTokenPair.mockResolvedValue(sampleUser);
    refreshAuthTokens.mockResolvedValue(null);
    logoutRemote.mockResolvedValue(undefined);
  });

  it("throws when useAuth is used outside AuthProvider", () => {
    expect(() => render(<AuthProbe />)).toThrow("useAuth must be used within AuthProvider");
  });

  it("bootstraps with no stored session", async () => {
    renderAuth();
    await waitFor(() => {
      expect(screen.getByTestId("loading")).toHaveTextContent("false");
    });
    expect(screen.getByTestId("user")).toHaveTextContent("none");
    expect(fetchCurrentUser).not.toHaveBeenCalled();
  });

  it("bootstraps with a stored session", async () => {
    hasStoredSession.mockReturnValue(true);
    renderAuth();
    await waitFor(() => {
      expect(screen.getByTestId("user")).toHaveTextContent("admin@test.com");
    });
    expect(screen.getByTestId("admin")).toHaveTextContent("true");
  });

  it("refreshes tokens when bootstrap fetch fails once", async () => {
    hasStoredSession.mockReturnValue(true);
    fetchCurrentUser
      .mockRejectedValueOnce(new Error("expired"))
      .mockResolvedValueOnce(sampleUser);
    refreshAuthTokens.mockResolvedValue(sampleTokens);

    renderAuth();
    await waitFor(() => {
      expect(screen.getByTestId("user")).toHaveTextContent("admin@test.com");
    });
    expect(refreshAuthTokens).toHaveBeenCalled();
  });

  it("clears tokens when bootstrap and refresh both fail", async () => {
    hasStoredSession.mockReturnValue(true);
    fetchCurrentUser.mockRejectedValue(new Error("expired"));
    refreshAuthTokens.mockResolvedValue(null);

    renderAuth();
    await waitFor(() => {
      expect(screen.getByTestId("loading")).toHaveTextContent("false");
    });
    expect(clearTokens).toHaveBeenCalled();
    expect(screen.getByTestId("user")).toHaveTextContent("none");
  });

  it("clears tokens when refresh succeeds but user fetch still fails", async () => {
    hasStoredSession.mockReturnValue(true);
    fetchCurrentUser
      .mockRejectedValueOnce(new Error("expired"))
      .mockRejectedValueOnce(new Error("still expired"));
    refreshAuthTokens.mockResolvedValue(sampleTokens);

    renderAuth();
    await waitFor(() => {
      expect(screen.getByTestId("loading")).toHaveTextContent("false");
    });
    expect(clearTokens).toHaveBeenCalled();
  });

  it("supports login, register, phone login, oauth, refresh, and logout", async () => {
    const user = userEvent.setup();
    renderAuth();
    await waitFor(() => {
      expect(screen.getByTestId("loading")).toHaveTextContent("false");
    });

    await user.click(screen.getByRole("button", { name: "login" }));
    await waitFor(() => {
      expect(screen.getByTestId("user")).toHaveTextContent("admin@test.com");
    });

    hasStoredSession.mockReturnValue(false);
    fetchCurrentUser.mockResolvedValue({ ...sampleUser, email: "new@test.com" });

    await user.click(screen.getByRole("button", { name: "register" }));
    await waitFor(() => {
      expect(registerWithEmailOtp).toHaveBeenCalled();
    });

    await user.click(screen.getByRole("button", { name: "phone-login" }));
    await waitFor(() => {
      expect(verifyPhoneOtp).toHaveBeenCalled();
    });

    await user.click(screen.getByRole("button", { name: "oauth" }));
    await waitFor(() => {
      expect(applyTokenPair).toHaveBeenCalledWith(sampleTokens);
    });

    await user.click(screen.getByRole("button", { name: "refresh" }));
    await waitFor(() => {
      expect(fetchCurrentUser).toHaveBeenCalled();
    });

    await user.click(screen.getByRole("button", { name: "logout" }));
    await waitFor(() => {
      expect(logoutRemote).toHaveBeenCalled();
      expect(screen.getByTestId("user")).toHaveTextContent("none");
    });
  });
});
