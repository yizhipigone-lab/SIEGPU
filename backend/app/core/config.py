from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "dev"
    database_url: str = "postgresql+psycopg://siegpu:pw@db:5432/siegpu"
    jwt_secret: str = "change-me-in-prod"
    jwt_algo: str = "HS256"
    access_token_expire_minutes: int = 1440
    vat_default: str = "0.13"
    upload_dir: str = "./uploads"

    # —— 智能助手（对话大脑，2026-08-27 P0）——
    # DeepSeek API（OpenAI 兼容协议）；key 只走 .env，绝不入库/入仓
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    assistant_model: str = "deepseek-chat"
    # 成本硬闸门（VERA claude_cli.py 同款纪律）：单轮工具调用上限 + 单用户日 token 配额
    assistant_max_tool_calls: int = 8
    assistant_daily_token_quota: int = 200000
    assistant_timeout_seconds: int = 120
    # M-A 认知层开关（回滚用：一键关闭注入/捕获）
    assistant_cognition_enabled: bool = True
    # M-C 写操作（默认全关；白名单动作逐个放开）
    assistant_writes_enabled: bool = False
    assistant_write_actions: str = "record_income"
    assistant_write_daily_limit: int = 20
    assistant_confirm_ttl_minutes: int = 5

    @model_validator(mode="after")
    def _check_jwt_secret(self) -> "Settings":
        # W4：生产环境禁用默认/弱 JWT secret——否则任何人可伪造任意角色 token
        if self.env == "prod" and self.jwt_secret in {"", "change-me-in-prod"}:
            raise ValueError("ENV=prod 时必须设置非默认的 JWT_SECRET")
        if self.env == "prod" and len(self.jwt_secret) < 32:
            raise ValueError("ENV=prod 时 JWT_SECRET 至少 32 字符")
        return self


settings = Settings()
