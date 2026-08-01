"""v3.2 向导式工作台 — 3 张新表。

Revision ID: 0003_wizard
Revises: 0002_v31
Create Date: 2026-08-01
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "0003_wizard"
down_revision = "0002_v31"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    conn = op.get_bind()
    return conn.dialect.has_table(conn, name)


def upgrade() -> None:
    if _has_table("workflow_templates"):
        print("  wizard tables already exist, skipping 0003")
        return

    op.create_table(
        "workflow_templates",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("steps", JSONB(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute("CREATE TRIGGER trg_workflow_templates_updated BEFORE UPDATE ON workflow_templates FOR EACH ROW EXECUTE FUNCTION set_updated_at()")

    op.create_table(
        "project_workflows",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id"), unique=True, nullable=False),
        sa.Column("template_id", UUID(as_uuid=True), sa.ForeignKey("workflow_templates.id"), nullable=True),
        sa.Column("steps", JSONB(), nullable=False),
        sa.Column("current_step", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(20), nullable=False, server_default="进行中"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_pw_project", "project_workflows", ["project_id"], unique=False, postgresql_where=sa.text("deleted_at IS NULL"))
    op.execute("CREATE TRIGGER trg_project_workflows_updated BEFORE UPDATE ON project_workflows FOR EACH ROW EXECUTE FUNCTION set_updated_at()")

    op.create_table(
        "step_audit_logs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_workflow_id", UUID(as_uuid=True), sa.ForeignKey("project_workflows.id"), nullable=False),
        sa.Column("step_seq", sa.Integer(), nullable=False),
        sa.Column("step_name", sa.String(100), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("operator_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("operated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("note", sa.Text(), nullable=True),
    )
    op.create_index("idx_sal_workflow", "step_audit_logs", ["project_workflow_id"])


def downgrade() -> None:
    op.drop_table("step_audit_logs")
    op.drop_table("project_workflows")
    op.drop_table("workflow_templates")
