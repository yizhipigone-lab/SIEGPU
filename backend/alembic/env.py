from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import settings
from app.models import Base  # 导入全部模型，供 autogenerate

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 由 .env 注入数据库 URL
config.set_main_option("sqlalchemy.url", settings.database_url)
target_metadata = Base.metadata


def include_object(object, name, type_, reflected, compare_to):
    """autogenerate 不管理 index：索引由 schema.sql/baseline 手动维护，
    避免模型未声明的索引被误判为 '需要 drop'。列/表/外键仍正常检测。"""
    if type_ == "index":
        return False
    return True


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            # compare_server_default 暂关：id/created_at 的 DB 默认与模型 Python 默认会被误判为 diff
            compare_server_default=False,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    raise RuntimeError("offline mode 未配置；请使用 online")
else:
    run_migrations_online()
