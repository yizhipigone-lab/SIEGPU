"""v3.1 全链路补齐 — 仅用于从 v2.0 库升级（新库 schema.sql 已含全部，本迁移跳过）。

Revision ID: 0002_v31
Revises: 0001_init
Create Date: 2026-08-01
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "0002_v31"
down_revision = "0001_init"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    conn = op.get_bind()
    return conn.dialect.has_table(conn, name)


def _has_column(table: str, column: str) -> bool:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    cols = [c["name"] for c in inspector.get_columns(table)]
    return column in cols


def upgrade() -> None:
    # 新库 schema.sql 已含全表/全列/全 CHECK，跳过所有增量
    if _has_table("sales_orders"):
        print("  v3.1 tables already exist (schema.sql baseline), skipping 0002")
        return

    # ========== 新表 ==========
    op.create_table(
        "sales_orders",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("contract_id", UUID(as_uuid=True), sa.ForeignKey("contracts.id"), nullable=False),
        sa.Column("equipment_model_id", UUID(as_uuid=True), sa.ForeignKey("equipment_models.id"), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("monthly_rent_per_unit", sa.Numeric(18, 2), nullable=False),
        sa.Column("total_monthly_rent", sa.Numeric(18, 2), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="待交付"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute("CREATE TRIGGER trg_sales_orders_updated BEFORE UPDATE ON sales_orders FOR EACH ROW EXECUTE FUNCTION set_updated_at()")
    op.create_index("idx_sales_orders_project", "sales_orders", ["project_id"], unique=False, postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index("idx_sales_orders_contract", "sales_orders", ["contract_id"], unique=False, postgresql_where=sa.text("deleted_at IS NULL"))

    for tbl, cols, idx_specs in [
        ("acceptance_records", [
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
            sa.Column("acceptance_type", sa.String(20), nullable=False),
            sa.Column("order_id", UUID(as_uuid=True), sa.ForeignKey("orders.id"), nullable=True),
            sa.Column("sales_order_id", UUID(as_uuid=True), sa.ForeignKey("sales_orders.id"), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="待验收"),
            sa.Column("inspector", sa.String(100), nullable=True),
            sa.Column("acceptance_date", sa.Date(), nullable=True),
            sa.Column("quantity_accepted", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("quantity_rejected", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("rejection_reason", sa.Text(), nullable=True),
            sa.Column("file_path", sa.String(500), nullable=True),
            sa.Column("attachments", JSONB(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        ], [("idx_acc_project", ["project_id"])], "trg_acceptance_records_updated"),
        ("funding_replacements", [
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
            sa.Column("leasing_process_id", UUID(as_uuid=True), sa.ForeignKey("leasing_processes.id"), nullable=False),
            sa.Column("original_txn_id", UUID(as_uuid=True), sa.ForeignKey("capital_transactions.id"), nullable=False),
            sa.Column("replacement_txn_id", UUID(as_uuid=True), sa.ForeignKey("capital_transactions.id"), nullable=False),
            sa.Column("amount", sa.Numeric(18, 2), nullable=False),
            sa.Column("source_type_replaced", sa.String(20), nullable=False),
            sa.Column("replacement_date", sa.Date(), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="已置换"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        ], [("idx_fr_project", ["project_id"]), ("idx_fr_leasing", ["leasing_process_id"])], "trg_funding_replacements_updated"),
        ("profit_scenarios", [
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("params_json", JSONB(), nullable=False),
            sa.Column("result_json", JSONB(), nullable=False),
            sa.Column("is_actual", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        ], [("idx_ps_project", ["project_id"])], "trg_profit_scenarios_updated"),
        ("service_confirmations", [
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("billing_id", UUID(as_uuid=True), sa.ForeignKey("billings.id"), unique=True, nullable=False),
            sa.Column("sales_order_id", UUID(as_uuid=True), sa.ForeignKey("sales_orders.id"), nullable=False),
            sa.Column("period_label", sa.String(20), nullable=False),
            sa.Column("file_path", sa.String(500), nullable=True),
            sa.Column("confirmed_by_customer", sa.String(100), nullable=True),
            sa.Column("confirmed_at", sa.Date(), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="待确认"),
            sa.Column("dispute_reason", sa.Text(), nullable=True),
            sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        ], [("idx_sc_sales_order", ["sales_order_id"])], "trg_service_confirmations_updated"),
    ]:
        op.create_table(tbl, *cols)
        for idx_name, idx_cols in idx_specs:
            op.create_index(idx_name, tbl, idx_cols, unique=False, postgresql_where=sa.text("deleted_at IS NULL"))
        op.execute(f"CREATE TRIGGER {tbl}_updated BEFORE UPDATE ON {tbl} FOR EACH ROW EXECUTE FUNCTION set_updated_at()")

    # ========== 现有表扩展 ==========
    # capital_transactions
    op.execute("ALTER TABLE capital_transactions DROP CONSTRAINT IF EXISTS capital_transactions_source_type_check")
    op.execute("ALTER TABLE capital_transactions ADD CONSTRAINT capital_transactions_source_type_check CHECK (source_type IN ('自有资金','银行流贷','金租融资','租金收入','调配','调配归还','还款','归还流贷','归还自有'))")
    if not _has_column("capital_transactions", "is_replaced"):
        op.add_column("capital_transactions", sa.Column("is_replaced", sa.Boolean(), nullable=False, server_default="false"))
    if not _has_column("capital_transactions", "replaced_amount"):
        op.add_column("capital_transactions", sa.Column("replaced_amount", sa.Numeric(18, 2), nullable=False, server_default="0"))
    op.create_index("idx_ct_replaced", "capital_transactions", ["project_id", "is_replaced"], unique=False, postgresql_where=sa.text("deleted_at IS NULL AND direction = 'OUT'"))

    # invoices
    op.execute("ALTER TABLE invoices DROP CONSTRAINT IF EXISTS invoices_status_check")
    op.execute("ALTER TABLE invoices ADD CONSTRAINT invoices_status_check CHECK (status IN ('待开','已开','待收票','已收票','已回款','已付款','已核销','已红冲'))")
    if not _has_column("invoices", "billing_id"):
        op.add_column("invoices", sa.Column("billing_id", UUID(as_uuid=True), nullable=True))
    if not _has_column("invoices", "purchase_order_id"):
        op.add_column("invoices", sa.Column("purchase_order_id", UUID(as_uuid=True), sa.ForeignKey("orders.id"), nullable=True))
    if not _has_column("invoices", "reconciled_at"):
        op.add_column("invoices", sa.Column("reconciled_at", sa.Date(), nullable=True))
    if not _has_column("invoices", "reconciled_by"):
        op.add_column("invoices", sa.Column("reconciled_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True))
    if not _has_column("invoices", "reconciliation_note"):
        op.add_column("invoices", sa.Column("reconciliation_note", sa.Text(), nullable=True))
    op.create_index("idx_inv_billing", "invoices", ["billing_id"], unique=False, postgresql_where=sa.text("billing_id IS NOT NULL"))

    # billings
    if not _has_column("billings", "sales_order_id"):
        op.add_column("billings", sa.Column("sales_order_id", UUID(as_uuid=True), sa.ForeignKey("sales_orders.id"), nullable=True))
    if not _has_column("billings", "confirmation_status"):
        op.add_column("billings", sa.Column("confirmation_status", sa.String(20), nullable=True))
    op.alter_column("billings", "order_id", existing_type=UUID(as_uuid=True), nullable=True)
    op.execute("DROP INDEX IF EXISTS uq_billing_period")
    op.create_index("uq_billing_period", "billings", ["sales_order_id", "period_index"], unique=True, postgresql_where=sa.text("deleted_at IS NULL AND sales_order_id IS NOT NULL"))
    op.create_index("idx_billing_order", "billings", ["order_id"], unique=False, postgresql_where=sa.text("deleted_at IS NULL AND order_id IS NOT NULL"))

    # audit_logs
    op.execute("ALTER TABLE audit_logs DROP CONSTRAINT IF EXISTS audit_logs_action_check")
    op.execute("ALTER TABLE audit_logs ADD CONSTRAINT audit_logs_action_check CHECK (action IN ('CREATE','UPDATE','DELETE','REVERSE','LOGIN','APPROVE_OVERCONTRACT','SUPERSEDE','ACCEPT_APPROVE','RECONCILE','RECONCILE_REVOKE','SUPERSEDE_REVOKE','CONFIRM_UPLOAD'))")


def downgrade() -> None:
    if _has_table("sales_orders"):
        op.drop_table("service_confirmations")
        op.drop_table("profit_scenarios")
        op.drop_table("funding_replacements")
        op.drop_table("acceptance_records")
        op.drop_table("sales_orders")
