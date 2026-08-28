"""0031 S12：金租申请「已作废」状态（缺陷#10，CHECK 只扩不收窄）。

downgrade 先清已作废行再收窄（0008/0011 guard 范式）。
"""
from alembic import op

revision = "0031_lease_void"
down_revision = "0030_disbursement_mode"
branch_labels = None
depends_on = None

_OLD = "'进行中','已批','已放款','已拒绝'"
_NEW = "'进行中','已批','已放款','已拒绝','已作废'"


def upgrade():
    op.execute("ALTER TABLE leasing_processes DROP CONSTRAINT IF EXISTS leasing_processes_status_check;")
    op.execute(f"ALTER TABLE leasing_processes ADD CONSTRAINT leasing_processes_status_check CHECK (status IN ({_NEW}));")


def downgrade():
    op.execute("DELETE FROM leasing_processes WHERE status = '已作废';")
    op.execute("ALTER TABLE leasing_processes DROP CONSTRAINT IF EXISTS leasing_processes_status_check;")
    op.execute(f"ALTER TABLE leasing_processes ADD CONSTRAINT leasing_processes_status_check CHECK (status IN ({_OLD}));")
