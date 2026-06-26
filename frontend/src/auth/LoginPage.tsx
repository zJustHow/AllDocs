import { FormEvent, useEffect, useState } from "react";
import { AllDocsIcon } from "../icons";
import { useI18n } from "../i18n";
import { sendPhoneOtp, sendRegisterEmailOtp, wechatAuthorizeUrl } from "./api";
import { useAuth } from "./AuthContext";

type AuthMethod = "email" | "phone";
type EmailMode = "login" | "register";

export default function LoginPage() {
  const { t } = useI18n();
  const { login, register, loginWithPhone } = useAuth();
  const [method, setMethod] = useState<AuthMethod>("email");
  const [emailMode, setEmailMode] = useState<EmailMode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [emailOtpCode, setEmailOtpCode] = useState("");
  const [phone, setPhone] = useState("");
  const [otpCode, setOtpCode] = useState("");
  const [emailOtpSent, setEmailOtpSent] = useState(false);
  const [otpSent, setOtpSent] = useState(false);
  const [emailOtpCooldown, setEmailOtpCooldown] = useState(0);
  const [otpCooldown, setOtpCooldown] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (emailOtpCooldown <= 0) return;
    const timer = window.setTimeout(() => {
      setEmailOtpCooldown((value) => Math.max(0, value - 1));
    }, 1000);
    return () => window.clearTimeout(timer);
  }, [emailOtpCooldown]);

  useEffect(() => {
    if (otpCooldown <= 0) return;
    const timer = window.setTimeout(() => {
      setOtpCooldown((value) => Math.max(0, value - 1));
    }, 1000);
    return () => window.clearTimeout(timer);
  }, [otpCooldown]);

  const handleSendEmailOtp = async () => {
    setSubmitting(true);
    setError(null);
    try {
      await sendRegisterEmailOtp(email.trim());
      setEmailOtpSent(true);
      setEmailOtpCooldown(60);
    } catch (err) {
      setError(String(err));
    } finally {
      setSubmitting(false);
    }
  };

  const handleSendOtp = async () => {
    setSubmitting(true);
    setError(null);
    try {
      await sendPhoneOtp(phone.trim());
      setOtpSent(true);
      setOtpCooldown(60);
    } catch (err) {
      setError(String(err));
    } finally {
      setSubmitting(false);
    }
  };

  const handleEmailLoginSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await login(email.trim(), password);
    } catch (err) {
      setError(String(err));
    } finally {
      setSubmitting(false);
    }
  };

  const handleEmailRegisterSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await register(
        email.trim(),
        emailOtpCode.trim(),
        password,
        displayName.trim() || undefined,
      );
    } catch (err) {
      setError(String(err));
    } finally {
      setSubmitting(false);
    }
  };

  const handlePhoneSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await loginWithPhone(phone.trim(), otpCode.trim());
    } catch (err) {
      setError(String(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="auth-page">
      <div className="auth-card auth-card-wide">
        <div className="auth-brand">
          <AllDocsIcon size={40} />
          <h1>{t("app.brand")}</h1>
          <p>{t("auth.subtitle")}</p>
        </div>

        <div
          className="auth-tabs auth-method-tabs"
          role="tablist"
          aria-label={t("auth.methodLabel")}
        >
          {(["email", "phone"] as const).map((item) => (
            <button
              key={item}
              type="button"
              role="tab"
              aria-selected={method === item}
              className={method === item ? "active" : ""}
              onClick={() => {
                setMethod(item);
                setError(null);
              }}
            >
              {t(`auth.method.${item}`)}
            </button>
          ))}
        </div>

        {method === "email" ? (
          <>
            {emailMode === "login" ? (
              <form className="auth-form" onSubmit={handleEmailLoginSubmit}>
                <label className="auth-field">
                  <span>{t("auth.email")}</span>
                  <input
                    type="email"
                    autoComplete="email"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder={t("auth.emailPlaceholder")}
                  />
                </label>

                <label className="auth-field">
                  <span>{t("auth.password")}</span>
                  <input
                    type="password"
                    autoComplete="current-password"
                    required
                    minLength={8}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder={t("auth.passwordPlaceholder")}
                  />
                </label>

                {error ? <div className="auth-error">{error}</div> : null}

                <button type="submit" className="auth-submit" disabled={submitting}>
                  {submitting ? t("auth.submitting") : t("auth.loginAction")}
                </button>
              </form>
            ) : (
              <form className="auth-form" onSubmit={handleEmailRegisterSubmit}>
                <label className="auth-field">
                  <span>{t("auth.displayName")}</span>
                  <input
                    type="text"
                    autoComplete="name"
                    value={displayName}
                    onChange={(e) => setDisplayName(e.target.value)}
                    placeholder={t("auth.displayNamePlaceholder")}
                  />
                </label>

                <label className="auth-field">
                  <span>{t("auth.email")}</span>
                  <input
                    type="email"
                    autoComplete="email"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder={t("auth.emailPlaceholder")}
                  />
                </label>

                <label className="auth-field">
                  <span>{t("auth.otpCode")}</span>
                  <div className="auth-otp-row">
                    <input
                      type="text"
                      inputMode="numeric"
                      autoComplete="one-time-code"
                      required
                      value={emailOtpCode}
                      onChange={(e) => setEmailOtpCode(e.target.value)}
                      placeholder={t("auth.otpPlaceholder")}
                    />
                    <button
                      type="button"
                      className="auth-otp-send"
                      disabled={submitting || emailOtpCooldown > 0 || !email.trim()}
                      onClick={() => void handleSendEmailOtp()}
                    >
                      {emailOtpCooldown > 0
                        ? t("auth.otpResendIn", { seconds: emailOtpCooldown })
                        : emailOtpSent
                          ? t("auth.otpResend")
                          : t("auth.otpSend")}
                    </button>
                  </div>
                </label>

                <label className="auth-field">
                  <span>{t("auth.password")}</span>
                  <input
                    type="password"
                    autoComplete="new-password"
                    required
                    minLength={8}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder={t("auth.passwordPlaceholder")}
                  />
                </label>

                <p className="auth-hint">{t("auth.emailRegisterHint")}</p>

                {error ? <div className="auth-error">{error}</div> : null}

                <button type="submit" className="auth-submit" disabled={submitting}>
                  {submitting ? t("auth.submitting") : t("auth.registerAction")}
                </button>
              </form>
            )}

            <p className="auth-mode-switch">
              {emailMode === "login" ? (
                <>
                  {t("auth.noAccount")}{" "}
                  <button
                    type="button"
                    className="auth-link"
                    onClick={() => {
                      setEmailMode("register");
                      setError(null);
                    }}
                  >
                    {t("auth.registerTab")}
                  </button>
                </>
              ) : (
                <>
                  {t("auth.hasAccount")}{" "}
                  <button
                    type="button"
                    className="auth-link"
                    onClick={() => {
                      setEmailMode("login");
                      setError(null);
                    }}
                  >
                    {t("auth.loginTab")}
                  </button>
                </>
              )}
            </p>
          </>
        ) : null}

        {method === "phone" ? (
          <form className="auth-form" onSubmit={handlePhoneSubmit}>
            <label className="auth-field">
              <span>{t("auth.phone")}</span>
              <input
                type="tel"
                autoComplete="tel"
                required
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                placeholder={t("auth.phonePlaceholder")}
              />
            </label>

            <label className="auth-field">
              <span>{t("auth.otpCode")}</span>
              <div className="auth-otp-row">
                <input
                  type="text"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  required
                  value={otpCode}
                  onChange={(e) => setOtpCode(e.target.value)}
                  placeholder={t("auth.otpPlaceholder")}
                />
                <button
                  type="button"
                  className="auth-otp-send"
                  disabled={submitting || otpCooldown > 0 || !phone.trim()}
                  onClick={() => void handleSendOtp()}
                >
                  {otpCooldown > 0
                    ? t("auth.otpResendIn", { seconds: otpCooldown })
                    : otpSent
                      ? t("auth.otpResend")
                      : t("auth.otpSend")}
                </button>
              </div>
            </label>

            <p className="auth-hint">{t("auth.phoneHint")}</p>

            {error ? <div className="auth-error">{error}</div> : null}

            <button type="submit" className="auth-submit" disabled={submitting}>
              {submitting ? t("auth.submitting") : t("auth.phoneLoginAction")}
            </button>
          </form>
        ) : null}

        <div className="auth-footer">
          <div className="auth-divider" aria-hidden="true">
            <span>{t("auth.or")}</span>
          </div>
          <a
            className="auth-alt-btn auth-wechat-btn"
            href={wechatAuthorizeUrl()}
            title={t("auth.wechatHint")}
          >
            {t("auth.wechatAction")}
          </a>
        </div>
      </div>
    </div>
  );
}
