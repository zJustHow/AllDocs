import AccountContent from "./auth/AccountContent";
import { useAuth } from "./auth/AuthContext";
import { ProfileIcon } from "./icons";
import { useI18n } from "./i18n";
import SubpageTopBar from "./SubpageTopBar";

interface ProfilePageProps {
  onLogout: () => Promise<void>;
}

function profileSubtitle(
  email: string | null,
  phone: string | null,
): string | null {
  if (email) return email;
  if (!phone) return null;
  const digits = phone.replace(/\D/g, "");
  if (digits.length < 4) return phone;
  return `****${digits.slice(-4)}`;
}

export default function ProfilePage({ onLogout }: ProfilePageProps) {
  const { t } = useI18n();
  const { user } = useAuth();

  const displayName = user
    ? (user.display_name ?? user.email ?? user.phone ?? t("account.unbound"))
    : null;
  const subtitle = user ? profileSubtitle(user.email, user.phone) : null;
  const roleLabel = user
    ? user.role === "admin"
      ? t("account.roleAdmin")
      : t("account.roleUser")
    : null;

  return (
    <div className="app subpage-app">
      <SubpageTopBar title={t("account.title")} />

      <div className="subpage-body">
        <div className="main subpage-main">
          <div className="subpage-content settings-page profile-page">
            <div className="settings-page-body">
              <div className="settings-page-shell profile-page-inner">
                {!user ? (
                  <p className="settings-page-status">{t("settings.loading")}</p>
                ) : (
                  <>
                    <section className="profile-hero" aria-label={t("account.profile")}>
                      <div className="profile-avatar" aria-hidden="true">
                        <ProfileIcon size={28} />
                      </div>
                      <div className="profile-hero-text">
                        <h2 className="profile-display-name">{displayName}</h2>
                        {subtitle && subtitle !== displayName ? (
                          <p className="profile-subtitle">{subtitle}</p>
                        ) : null}
                        <span
                          className={`profile-role-badge ${user.role === "admin" ? "is-admin" : ""}`}
                        >
                          {roleLabel}
                        </span>
                      </div>
                    </section>

                    <AccountContent />

                    <section className="profile-logout-section">
                      <button
                        type="button"
                        className="profile-logout-btn"
                        onClick={() => void onLogout()}
                      >
                        {t("auth.logout")}
                      </button>
                    </section>
                  </>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
