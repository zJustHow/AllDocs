import { FormEvent, useEffect, useState } from "react";
import { useI18n } from "../i18n";
import {
  bindEmail,
  bindPhone,
  sendBindPhoneOtp,
  unbindIdentity,
  type BindProvider,
  wechatBindAuthorizeUrl,
} from "./api";
import { useAuth } from "./AuthContext";

function maskPhone(phone: string | null): string | null {
  if (!phone) return null;
  const digits = phone.replace(/\D/g, "");
  if (digits.length < 4) return phone;
  return `****${digits.slice(-4)}`;
}

export default function AccountContent() {
  const { t } = useI18n();
  const { user, refreshUser } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [phone, setPhone] = useState("");
  const [otpCode, setOtpCode] = useState("");
  const [otpSent, setOtpSent] = useState(false);
  const [otpCooldown, setOtpCooldown] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (otpCooldown <= 0) return;
    const timer = window.setTimeout(() => {
      setOtpCooldown((value) => Math.max(0, value - 1));
    }, 1000);
    return () => window.clearTimeout(timer);
  }, [otpCooldown]);

  if (!user) return null;

  const boundMethodCount =
    Number(Boolean(user.email)) + Number(Boolean(user.phone)) + Number(Boolean(user.wechat_bound));
  const canUnbind = boundMethodCount > 1;

  const handleUnbind = async (provider: BindProvider) => {
    if (!window.confirm(t("account.unbindConfirm"))) return;
    setSubmitting(true);
    setError(null);
    setNotice(null);
    try {
      await unbindIdentity(provider);
      await refreshUser();
      setNotice(t("account.unbindSuccess"));
    } catch (err) {
      setError(String(err));
    } finally {
      setSubmitting(false);
    }
  };

  const handleBindEmail = async (event: FormEvent) => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    setNotice(null);
    try {
      await bindEmail(email.trim(), password);
      await refreshUser();
      setEmail("");
      setPassword("");
      setNotice(t("account.emailBound"));
    } catch (err) {
      setError(String(err));
    } finally {
      setSubmitting(false);
    }
  };

  const handleSendOtp = async () => {
    setSubmitting(true);
    setError(null);
    setNotice(null);
    try {
      await sendBindPhoneOtp(phone.trim());
      setOtpSent(true);
      setOtpCooldown(60);
    } catch (err) {
      setError(String(err));
    } finally {
      setSubmitting(false);
    }
  };

  const handleBindPhone = async (event: FormEvent) => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    setNotice(null);
    try {
      await bindPhone(phone.trim(), otpCode.trim());
      await refreshUser();
      setPhone("");
      setOtpCode("");
      setOtpSent(false);
      setNotice(t("account.phoneBound"));
    } catch (err) {
      setError(String(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="profile-sections">
      {error ? <div className="banner error profile-banner">{error}</div> : null}
      {notice ? <div className="banner profile-banner">{notice}</div> : null}

      <section className="profile-card">
        <h3 className="profile-card-title">{t("account.bindings")}</h3>
        <ul className="profile-binding-list">
          <li className="profile-binding-row">
            <span className="profile-binding-label">{t("auth.email")}</span>
            <div className="profile-binding-value">
              <strong>{user.email ?? t("account.unbound")}</strong>
              {user.email && canUnbind ? (
                <button
                  type="button"
                  className="account-unbind-btn"
                  disabled={submitting}
                  onClick={() => void handleUnbind("email")}
                >
                  {t("account.unbind")}
                </button>
              ) : null}
            </div>
          </li>
          <li className="profile-binding-row">
            <span className="profile-binding-label">{t("auth.phone")}</span>
            <div className="profile-binding-value">
              <strong>{maskPhone(user.phone) ?? t("account.unbound")}</strong>
              {user.phone && canUnbind ? (
                <button
                  type="button"
                  className="account-unbind-btn"
                  disabled={submitting}
                  onClick={() => void handleUnbind("phone")}
                >
                  {t("account.unbind")}
                </button>
              ) : null}
            </div>
          </li>
          <li className="profile-binding-row">
            <span className="profile-binding-label">{t("auth.method.wechat")}</span>
            <div className="profile-binding-value">
              <strong>{user.wechat_bound ? t("account.bound") : t("account.unbound")}</strong>
              {user.wechat_bound && canUnbind ? (
                <button
                  type="button"
                  className="account-unbind-btn"
                  disabled={submitting}
                  onClick={() => void handleUnbind("wechat")}
                >
                  {t("account.unbind")}
                </button>
              ) : null}
            </div>
          </li>
        </ul>
      </section>

      {!user.email ? (
        <section className="profile-card">
          <h3 className="profile-card-title">{t("account.bindEmail")}</h3>
          <form className="auth-form profile-form" onSubmit={handleBindEmail}>
            <label className="auth-field">
              <span>{t("auth.email")}</span>
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </label>
            <label className="auth-field">
              <span>{t("auth.password")}</span>
              <input
                type="password"
                required
                minLength={8}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </label>
            <button type="submit" className="auth-submit" disabled={submitting}>
              {t("account.bindAction")}
            </button>
          </form>
        </section>
      ) : null}

      {!user.phone ? (
        <section className="profile-card">
          <h3 className="profile-card-title">{t("account.bindPhone")}</h3>
          <form className="auth-form profile-form" onSubmit={handleBindPhone}>
            <label className="auth-field">
              <span>{t("auth.phone")}</span>
              <input
                type="tel"
                required
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
              />
            </label>
            <label className="auth-field">
              <span>{t("auth.otpCode")}</span>
              <div className="auth-otp-row">
                <input
                  type="text"
                  inputMode="numeric"
                  required
                  value={otpCode}
                  onChange={(e) => setOtpCode(e.target.value)}
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
            <button type="submit" className="auth-submit" disabled={submitting}>
              {t("account.bindAction")}
            </button>
          </form>
        </section>
      ) : null}

      {!user.wechat_bound ? (
        <section className="profile-card">
          <h3 className="profile-card-title">{t("account.bindWechat")}</h3>
          <a className="auth-submit profile-wechat-btn" href={wechatBindAuthorizeUrl()}>
            {t("account.bindWechatAction")}
          </a>
        </section>
      ) : null}
    </div>
  );
}
