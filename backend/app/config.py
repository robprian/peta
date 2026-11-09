from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str = "postgresql://peta:peta_secret@localhost:5432/peta"
    db_pool_min: int = 2
    db_pool_max: int = 10
    statement_timeout_ms: int = 5000

    cors_origins: str = "*"
    api_keys: str = ""
    rate_limit_per_minute: int = 120
    cache_ttl_seconds: int = 86400

    photon_url: str = ""
    nominatim_url: str = ""
    tile_url: str = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
    tile_attribution: str = "&copy; OpenStreetMap contributors"

    @property
    def cors_origin_list(self) -> list[str]:
        value = self.cors_origins.strip()
        if value == "*":
            return ["*"]
        return [origin.strip() for origin in value.split(",") if origin.strip()]

    @property
    def api_key_set(self) -> set[str]:
        return {key.strip() for key in self.api_keys.split(",") if key.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
