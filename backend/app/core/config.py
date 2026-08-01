from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "dev"
    database_url: str = "postgresql+psycopg://siegpu:pw@db:5432/siegpu"
    jwt_secret: str = "change-me-in-prod"
    jwt_algo: str = "HS256"
    access_token_expire_minutes: int = 30
    vat_default: str = "0.13"
    upload_dir: str = "./uploads"

    @model_validator(mode="after")
    def _check_jwt_secret(self) -> "Settings":
        # W4：生产环境禁用默认/弱 JWT secret——否则任何人可伪造任意角色 token
        if self.env == "prod" and self.jwt_secret in {"", "change-me-in-prod"}:
            raise ValueError("ENV=prod 时必须设置非默认的 JWT_SECRET")
        if self.env == "prod" and len(self.jwt_secret) < 32:
            raise ValueError("ENV=prod 时 JWT_SECRET 至少 32 字符")
        return self


settings = Settings()
