from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "de52253236eb"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "classes",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("grade", sa.SmallInteger(), nullable=True),
        sa.Column("max_chat_id", sa.BigInteger(), nullable=True),
        sa.Column("invite_code", sa.String(length=32), nullable=False),
        sa.Column(
            "bot_can_read_chat", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_classes")),
        sa.UniqueConstraint("invite_code", name=op.f("uq_classes_invite_code")),
        sa.UniqueConstraint("max_chat_id", name=op.f("uq_classes_max_chat_id")),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("max_user_id", sa.BigInteger(), nullable=False),
        sa.Column("first_name", sa.String(length=200), server_default="", nullable=False),
        sa.Column("last_name", sa.String(length=200), nullable=True),
        sa.Column("username", sa.String(length=200), nullable=True),
        sa.Column(
            "role",
            sa.Enum("student", "teacher", name="user_role"),
            server_default="student",
            nullable=False,
        ),
        sa.Column("class_id", sa.BigInteger(), nullable=True),
        sa.Column("grade", sa.SmallInteger(), nullable=True),
        sa.Column(
            "consent_status",
            sa.Enum("none", "pending", "granted", "revoked", name="consent_status"),
            server_default="none",
            nullable=False,
        ),
        sa.Column("consented_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dialog_available", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["class_id"],
            ["classes.id"],
            name=op.f("fk_users_class_id_classes"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("max_user_id", name=op.f("uq_users_max_user_id")),
    )
    op.create_index(op.f("ix_users_class_id"), "users", ["class_id"], unique=False)
    op.create_table(
        "exams",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("class_id", sa.BigInteger(), nullable=True),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("subject", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column(
            "topic_codes",
            postgresql.ARRAY(sa.String(length=32)),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("scheduled_on", sa.Date(), nullable=False),
        sa.Column(
            "source", sa.Enum("student", "chat", "teacher", name="exam_source"), nullable=False
        ),
        sa.Column("source_mid", sa.String(length=100), nullable=True),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "class_id IS NOT NULL OR user_id IS NOT NULL", name=op.f("ck_exams_owner")
        ),
        sa.ForeignKeyConstraint(
            ["class_id"], ["classes.id"], name=op.f("fk_exams_class_id_classes"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_exams_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_exams")),
    )
    op.create_index("ix_exams_scheduled_on", "exams", ["scheduled_on"], unique=False)
    op.create_table(
        "notifications",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("ref", sa.String(length=128), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_notifications_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
        sa.UniqueConstraint("user_id", "kind", "ref", name=op.f("uq_notifications_user_id")),
    )
    op.create_table(
        "submissions",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum("homework", "material", "answer", name="submission_kind"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "processing",
                "needs_confirmation",
                "done",
                "failed",
                name="submission_status",
            ),
            server_default="queued",
            nullable=False,
        ),
        sa.Column("image_key", sa.String(length=300), nullable=True),
        sa.Column("image_sha256", sa.String(length=64), nullable=True),
        sa.Column("source_mid", sa.String(length=100), nullable=True),
        sa.Column("transcription", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("analysis", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("topic_code", sa.String(length=32), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_submissions_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_submissions")),
    )
    op.create_index(
        "ix_submissions_user_created", "submissions", ["user_id", "created_at"], unique=False
    )
    op.create_table(
        "topic_progress",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("topic_code", sa.String(length=32), nullable=False),
        sa.Column("mistakes_total", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("correct_total", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("box", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_mistake_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_practice_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_review_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_topic_progress_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "topic_code", name=op.f("pk_topic_progress")),
    )
    op.create_index("ix_topic_progress_due", "topic_progress", ["next_review_at"], unique=False)
    op.create_table(
        "materials",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("class_id", sa.BigInteger(), nullable=False),
        sa.Column("uploader_id", sa.BigInteger(), nullable=True),
        sa.Column("submission_id", sa.BigInteger(), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=True),
        sa.Column("content", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "topic_codes",
            postgresql.ARRAY(sa.String(length=32)),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["class_id"],
            ["classes.id"],
            name=op.f("fk_materials_class_id_classes"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["submission_id"],
            ["submissions.id"],
            name=op.f("fk_materials_submission_id_submissions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["uploader_id"],
            ["users.id"],
            name=op.f("fk_materials_uploader_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_materials")),
    )
    op.create_index(op.f("ix_materials_class_id"), "materials", ["class_id"], unique=False)
    op.create_table(
        "quizzes",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("exam_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "reason", sa.Enum("exam", "review", "manual", name="quiz_reason"), nullable=False
        ),
        sa.Column(
            "status",
            sa.Enum("active", "completed", "expired", name="quiz_status"),
            server_default="active",
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["exam_id"], ["exams.id"], name=op.f("fk_quizzes_exam_id_exams"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_quizzes_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quizzes")),
    )
    op.create_index(op.f("ix_quizzes_user_id"), "quizzes", ["user_id"], unique=False)
    op.create_table(
        "quiz_items",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("quiz_id", sa.BigInteger(), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("topic_code", sa.String(length=32), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("choices", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("correct_index", sa.SmallInteger(), nullable=False),
        sa.Column("answered_index", sa.SmallInteger(), nullable=True),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["quiz_id"],
            ["quizzes.id"],
            name=op.f("fk_quiz_items_quiz_id_quizzes"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quiz_items")),
        sa.UniqueConstraint("quiz_id", "position", name=op.f("uq_quiz_items_quiz_id")),
    )
    op.create_table(
        "mistakes",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("submission_id", sa.BigInteger(), nullable=True),
        sa.Column("quiz_item_id", sa.BigInteger(), nullable=True),
        sa.Column("topic_code", sa.String(length=32), nullable=False),
        sa.Column("error_type", sa.String(length=64), nullable=False),
        sa.Column("step_index", sa.SmallInteger(), nullable=True),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["quiz_item_id"],
            ["quiz_items.id"],
            name=op.f("fk_mistakes_quiz_item_id_quiz_items"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["submission_id"],
            ["submissions.id"],
            name=op.f("fk_mistakes_submission_id_submissions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_mistakes_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mistakes")),
    )
    op.create_index("ix_mistakes_user_topic", "mistakes", ["user_id", "topic_code"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_mistakes_user_topic", table_name="mistakes")
    op.drop_table("mistakes")
    op.drop_table("quiz_items")
    op.drop_index(op.f("ix_quizzes_user_id"), table_name="quizzes")
    op.drop_table("quizzes")
    op.drop_index(op.f("ix_materials_class_id"), table_name="materials")
    op.drop_table("materials")
    op.drop_index("ix_topic_progress_due", table_name="topic_progress")
    op.drop_table("topic_progress")
    op.drop_index("ix_submissions_user_created", table_name="submissions")
    op.drop_table("submissions")
    op.drop_table("notifications")
    op.drop_index("ix_exams_scheduled_on", table_name="exams")
    op.drop_table("exams")
    op.drop_index(op.f("ix_users_class_id"), table_name="users")
    op.drop_table("users")
    op.drop_table("classes")
    sa.Enum(name="quiz_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="quiz_reason").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="submission_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="submission_kind").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="exam_source").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="consent_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="user_role").drop(op.get_bind(), checkfirst=True)
