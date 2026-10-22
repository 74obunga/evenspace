from functools import lru_cache
import os


class Settings:
    """Environment-backed application settings."""

    @property
    def database_url(self) -> str:
        return os.getenv(
            "DATABASE_URL",
            "postgresql+psycopg://evenspace:evenspace-dev-only@localhost:5432/evenspace",
        )

    @property
    def app_name(self) -> str:
        return os.getenv("APP_NAME", "EvenSpace API")

    @property
    def session_cookie_name(self) -> str:
        return os.getenv("SESSION_COOKIE_NAME", "evenspace_session")

    @property
    def csrf_cookie_name(self) -> str:
        return os.getenv("CSRF_COOKIE_NAME", "evenspace_csrf")

    @property
    def session_cookie_secure(self) -> bool:
        return os.getenv("SESSION_COOKIE_SECURE", "true").lower() in {"1", "true", "yes"}

    @property
    def session_ttl_seconds(self) -> int:
        return int(os.getenv("SESSION_TTL_SECONDS", str(8 * 60 * 60)))

    @property
    def frontend_origin(self) -> str:
        return os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")

    @property
    def payment_provider(self) -> str:
        return os.getenv("PAYMENT_PROVIDER", "none").strip().lower()

    @property
    def daraja_environment(self) -> str:
        return os.getenv("DARAJA_ENVIRONMENT", "sandbox").strip().lower()

    @property
    def daraja_consumer_key(self) -> str | None:
        return os.getenv("DARAJA_CONSUMER_KEY")

    @property
    def daraja_consumer_secret(self) -> str | None:
        return os.getenv("DARAJA_CONSUMER_SECRET")

    @property
    def daraja_shortcode(self) -> str | None:
        return os.getenv("DARAJA_SHORTCODE")

    @property
    def daraja_passkey(self) -> str | None:
        return os.getenv("DARAJA_PASSKEY")

    @property
    def daraja_callback_base_url(self) -> str | None:
        return os.getenv("DARAJA_CALLBACK_BASE_URL")

    @property
    def daraja_transaction_type(self) -> str:
        return os.getenv("DARAJA_TRANSACTION_TYPE", "CustomerPayBillOnline").strip()

    @property
    def daraja_ready(self) -> bool:
        callback = self.daraja_callback_base_url or ""
        return self.payment_provider == "daraja" and all((
            self.daraja_environment in {"sandbox", "production"},
            self.daraja_consumer_key,
            self.daraja_consumer_secret,
            self.daraja_shortcode,
            self.daraja_passkey,
            callback.startswith("https://"),
        ))

    @property
    def smtp_host(self) -> str | None:
        return os.getenv("SMTP_HOST") or None

    @property
    def smtp_port(self) -> int:
        return int(os.getenv("SMTP_PORT", "587"))

    @property
    def smtp_username(self) -> str | None:
        return os.getenv("SMTP_USERNAME") or None

    @property
    def smtp_password(self) -> str | None:
        return os.getenv("SMTP_PASSWORD") or None

    @property
    def smtp_from_email(self) -> str:
        return os.getenv("SMTP_FROM_EMAIL", "notifications@evenspace.local")

    @property
    def smtp_starttls(self) -> bool:
        return os.getenv("SMTP_STARTTLS", "true").lower() in {"1", "true", "yes"}

    @property
    def notification_encryption_key(self) -> str | None:
        return os.getenv("NOTIFICATION_ENCRYPTION_KEY") or None


@lru_cache
def get_settings() -> Settings:
    return Settings()

