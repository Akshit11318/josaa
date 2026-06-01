"""initial schema: institutes, programs, cutoffs, seat_matrix, crawl_runs

Revision ID: 0001
Revises:
Create Date: 2026-06-01

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "institutes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("type", sa.String(length=10), nullable=False),
        sa.UniqueConstraint("name", name="uq_institute_name"),
    )
    op.create_index("ix_institutes_name", "institutes", ["name"])
    op.create_index("ix_institutes_type", "institutes", ["type"])

    op.create_table(
        "programs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=500), nullable=False),
        sa.UniqueConstraint("name", name="uq_program_name"),
    )
    op.create_index("ix_programs_name", "programs", ["name"])

    op.create_table(
        "cutoffs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("round", sa.Integer(), nullable=False),
        sa.Column("institute_id", sa.Integer(), sa.ForeignKey("institutes.id"), nullable=False),
        sa.Column("program_id", sa.Integer(), sa.ForeignKey("programs.id"), nullable=False),
        sa.Column("quota", sa.String(length=10), nullable=False),
        sa.Column("seat_type", sa.String(length=30), nullable=False),
        sa.Column("gender", sa.String(length=60), nullable=False),
        sa.Column("opening_rank", sa.Integer(), nullable=True),
        sa.Column("closing_rank", sa.Integer(), nullable=True),
        sa.Column("opening_rank_raw", sa.String(length=20), nullable=True),
        sa.Column("closing_rank_raw", sa.String(length=20), nullable=True),
        sa.Column("scraped_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "year", "round", "institute_id", "program_id", "quota", "seat_type", "gender",
            name="uq_cutoff",
        ),
    )
    op.create_index("ix_cutoffs_year", "cutoffs", ["year"])
    op.create_index("ix_cutoffs_round", "cutoffs", ["round"])
    op.create_index("ix_cutoffs_institute_id", "cutoffs", ["institute_id"])
    op.create_index("ix_cutoffs_program_id", "cutoffs", ["program_id"])
    op.create_index("ix_cutoffs_seat_type", "cutoffs", ["seat_type"])
    op.create_index("ix_cutoffs_gender", "cutoffs", ["gender"])
    op.create_index("ix_cutoffs_closing_rank", "cutoffs", ["closing_rank"])

    op.create_table(
        "seat_matrix",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("institute_id", sa.Integer(), sa.ForeignKey("institutes.id"), nullable=False),
        sa.Column("program_id", sa.Integer(), sa.ForeignKey("programs.id"), nullable=False),
        sa.Column("quota", sa.String(length=10), nullable=False),
        sa.Column("seat_type", sa.String(length=30), nullable=False),
        sa.Column("gender", sa.String(length=60), nullable=False),
        sa.Column("seats", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("scraped_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "year", "institute_id", "program_id", "quota", "seat_type", "gender",
            name="uq_seat_matrix",
        ),
    )
    op.create_index("ix_seat_matrix_year", "seat_matrix", ["year"])
    op.create_index("ix_seat_matrix_institute_id", "seat_matrix", ["institute_id"])
    op.create_index("ix_seat_matrix_program_id", "seat_matrix", ["program_id"])
    op.create_index("ix_seat_matrix_seat_type", "seat_matrix", ["seat_type"])
    op.create_index("ix_seat_matrix_gender", "seat_matrix", ["gender"])

    op.create_table(
        "crawl_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("page", sa.String(length=20), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("round", sa.Integer(), nullable=True),
        sa.Column("institute_type", sa.String(length=10), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("crawl_runs")
    op.drop_table("seat_matrix")
    op.drop_table("cutoffs")
    op.drop_table("programs")
    op.drop_table("institutes")
