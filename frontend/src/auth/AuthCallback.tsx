import { useEffect, useState } from "react";
import { useAuth } from "./AuthContext";
import { useI18n } from "../i18n";

function readOAuthTokensFromHash(): { access_token: string; refresh_token: string } | null {
  const hash = window.location.hash.startsWith("#")
    ? window.location.hash.slice(1)
    : window.location.hash;
  if (!hash) return null;
  const params = new URLSearchParams(hash);
  const access_token = params.get("access_token");
  const refresh_token = params.get("refresh_token");
  if (!access_token || !refresh_token) return null;
  return { access_token, refresh_token };
}

function readBindResultFromHash(): { provider: string; status: string } | null {
  const hash = window.location.hash.startsWith("#")
    ? window.location.hash.slice(1)
    : window.location.hash;
  if (!hash) return null;
  const params = new URLSearchParams(hash);
  const provider = params.get("bind");
  const status = params.get("status");
  if (!provider || !status) return null;
  return { provider, status };
}

export default function AuthCallback() {
  const { t } = useI18n();
  const { completeOAuthLogin, refreshUser } = useAuth();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const bindResult = readBindResultFromHash();
    if (bindResult) {
      void (async () => {
        try {
          if (bindResult.status !== "ok") {
            throw new Error(t("auth.oauthMissingTokens"));
          }
          await refreshUser();
          window.history.replaceState({}, "", "/");
        } catch (err) {
          setError(String(err));
        }
      })();
      return;
    }

    const tokens = readOAuthTokensFromHash();
    if (!tokens) {
      setError(t("auth.oauthMissingTokens"));
      return;
    }

    void (async () => {
      try {
        await completeOAuthLogin(tokens);
        window.history.replaceState({}, "", "/");
      } catch (err) {
        setError(String(err));
      }
    })();
  }, [completeOAuthLogin, refreshUser, t]);

  return (
    <div className="auth-page">
      <div className="auth-card">
        {error ? (
          <div className="auth-error">{error}</div>
        ) : (
          <p className="auth-loading-text">{t("auth.oauthCompleting")}</p>
        )}
      </div>
    </div>
  );
}
