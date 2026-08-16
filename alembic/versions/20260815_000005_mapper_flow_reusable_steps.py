"""make mapper flow steps reusable across flows

Revision ID: 20260815_000005
Revises: 20260815_000004
Create Date: 2026-08-15 20:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260815_000005"
down_revision = "20260815_000004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) new association table: (flow, step, ordinal). A step stops being owned by one flow.
    op.create_table(
        "mapper_flow_step_usages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("flow_id", sa.Integer(), sa.ForeignKey("mapper_flows.id", ondelete="CASCADE"), nullable=False),
        sa.Column("step_id", sa.Integer(), sa.ForeignKey("mapper_flow_steps.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.UniqueConstraint("flow_id", "step_id", name="uq_mapper_flow_step_usage"),
    )
    op.create_index("ix_mapper_flow_step_usages_flow_id_ordinal", "mapper_flow_step_usages", ["flow_id", "ordinal"])

    # 2) carry over every existing (flow_id, id, ordinal) from mapper_flow_steps into the new
    # usage table before the old columns are dropped, so no existing flow composition is lost.
    op.execute(
        "INSERT INTO mapper_flow_step_usages (flow_id, step_id, ordinal) "
        "SELECT flow_id, id, ordinal FROM mapper_flow_steps"
    )

    # 3) steps become package-scoped, reusable components instead of flow-owned rows.
    with op.batch_alter_table("mapper_flow_steps") as batch_op:
        batch_op.add_column(sa.Column("package_name", sa.String(length=160), nullable=False, server_default=""))
        batch_op.add_column(sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()))

    op.execute(
        "UPDATE mapper_flow_steps SET package_name = ("
        "  SELECT mapper_flows.package_name FROM mapper_flows WHERE mapper_flows.id = mapper_flow_steps.flow_id"
        ") WHERE EXISTS (SELECT 1 FROM mapper_flows WHERE mapper_flows.id = mapper_flow_steps.flow_id)"
    )

    # the old index is fully superseded by ix_mapper_flow_step_usages_flow_id_ordinal above, and
    # must go before the columns it's built on do: SQLite's batch mode rebuilds the table from
    # scratch and tries to recreate every index it saw on the old one, which fails once flow_id
    # and ordinal are gone (issue #42, hit the first time this migration ran against an empty DB).
    op.drop_index("ix_mapper_flow_steps_flow_id_ordinal", table_name="mapper_flow_steps")

    with op.batch_alter_table("mapper_flow_steps") as batch_op:
        batch_op.drop_column("flow_id")
        batch_op.drop_column("ordinal")


def downgrade() -> None:
    with op.batch_alter_table("mapper_flow_steps") as batch_op:
        batch_op.add_column(sa.Column("flow_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("ordinal", sa.Integer(), nullable=True))

    op.execute(
        "UPDATE mapper_flow_steps SET "
        "flow_id = (SELECT flow_id FROM mapper_flow_step_usages WHERE mapper_flow_step_usages.step_id = mapper_flow_steps.id LIMIT 1), "
        "ordinal = (SELECT ordinal FROM mapper_flow_step_usages WHERE mapper_flow_step_usages.step_id = mapper_flow_steps.id LIMIT 1)"
    )

    with op.batch_alter_table("mapper_flow_steps") as batch_op:
        batch_op.alter_column("flow_id", nullable=False)
        batch_op.alter_column("ordinal", nullable=False)
        batch_op.drop_column("created_at")
        batch_op.drop_column("package_name")

    # mirrors the drop in upgrade(): restores the index 000003's own downgrade() expects to
    # find (and drops by name) on mapper_flow_steps.
    op.create_index("ix_mapper_flow_steps_flow_id_ordinal", "mapper_flow_steps", ["flow_id", "ordinal"])

    op.drop_index("ix_mapper_flow_step_usages_flow_id_ordinal", table_name="mapper_flow_step_usages")
    op.drop_table("mapper_flow_step_usages")
