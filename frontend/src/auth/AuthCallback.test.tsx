/** @vitest-environment jsdom */
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AuthCallback from "./AuthCallback";
import { I18nProvider } from "../i18n";

const completeOAuthLogin = vi.fn();
const refreshUser = vi.fn();
const replaceState = vi.fn();

vi.mock("./AuthContext", () => ({
  useAuth: () => ({
    completeOAuthLogin,
    refreshUser,
  }),
}));

function renderPage() {
  return render(
    <I18nProvider>
      <AuthCallback />
    </I18nProvider>,
  );
}

describe("AuthCallback", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    completeOAuthLogin.mockResolvedValue(undefined);
    refreshUser.mockResolvedValue(undefined);
    window.history.replaceState = replaceState;
    window.location.hash = "";
  });

  it("shows an error when OAuth tokens are missing", async () => {
    renderPage();
    expect(
      await screen.findByText(/missing authorization data/i),
    ).toBeInTheDocument();
  });

  it("completes OAuth login from the hash", async () => {
    window.location.hash =
      "#access_token=access-token&refresh_token=refresh-token&token_type=bearer";
    renderPage();

    await waitFor(() => {
      expect(completeOAuthLogin).toHaveBeenCalledWith({
        access_token: "access-token",
        refresh_token: "refresh-token",
      });
      expect(replaceState).toHaveBeenCalledWith({}, "", "/");
    });
  });

  it("refreshes the user after a successful bind callback", async () => {
    window.location.hash = "#bind=wechat&status=ok";
    renderPage();

    await waitFor(() => {
      expect(refreshUser).toHaveBeenCalled();
      expect(replaceState).toHaveBeenCalledWith({}, "", "/");
    });
  });

  it("shows an error when bind callback status is not ok", async () => {
    window.location.hash = "#bind=wechat&status=failed";
    renderPage();

    expect(
      await screen.findByText(/missing authorization data/i),
    ).toBeInTheDocument();
  });

  it("shows an error when OAuth completion fails", async () => {
    completeOAuthLogin.mockRejectedValue(new Error("OAuth failed"));
    window.location.hash = "#access_token=access-token&refresh_token=refresh-token";
    renderPage();

    expect(await screen.findByText(/OAuth failed/i)).toBeInTheDocument();
  });
});
