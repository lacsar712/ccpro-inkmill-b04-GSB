"""轻量、幂等的启动期迁移。

项目使用 ``Base.metadata.create_all`` 建表，不会自动给已存在的表补列。
这里在应用启动时处理 GrindPass.ended_at 的引入：

1. 旧表缺少 ``ended_at`` 时补列；
2. 历史行全部按既有 duration_min 回填为“已结束”；
3. 增加生成列 + 唯一索引，在数据库层保证同一台研磨机至多一条进行中遍次。
"""

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.database import engine


def _has_column(conn, table: str, column: str) -> bool:
    return bool(
        conn.execute(
            text(
                "SELECT COUNT(*) FROM information_schema.columns "
                "WHERE table_schema = DATABASE() AND table_name = :t AND column_name = :c"
            ),
            {"t": table, "c": column},
        ).scalar()
    )


def _has_index(conn, table: str, index: str) -> bool:
    return bool(
        conn.execute(
            text(
                "SELECT COUNT(*) FROM information_schema.statistics "
                "WHERE table_schema = DATABASE() AND table_name = :t AND index_name = :i"
            ),
            {"t": table, "i": index},
        ).scalar()
    )


def _ensure_grind_passes_open_constraint(conn) -> None:
    # 历史行回填：旧数据全部视为已结束，ended_at 由既有 duration_min 推出
    conn.execute(
        text(
            "UPDATE grind_passes "
            "SET ended_at = DATE_ADD(started_at, INTERVAL duration_min * 60 SECOND) "
            "WHERE ended_at IS NULL AND duration_min > 0"
        )
    )

    # MySQL 唯一索引允许多个 NULL：仅进行中(ended_at IS NULL)的行参与唯一约束
    if not _has_column(conn, "grind_passes", "open_mill_id"):
        conn.execute(
            text(
                "ALTER TABLE grind_passes "
                "ADD COLUMN open_mill_id INT GENERATED ALWAYS AS "
                "(CASE WHEN ended_at IS NULL THEN mill_id ELSE NULL END) VIRTUAL"
            )
        )
    if not _has_index(conn, "grind_passes", "uq_grind_pass_open_mill"):
        conn.execute(
            text(
                "CREATE UNIQUE INDEX uq_grind_pass_open_mill "
                "ON grind_passes (open_mill_id)"
            )
        )


def run_light_migrations(bind: Engine | None = None) -> None:
    bind = bind or engine
    if bind.dialect.name != "mysql":
        # SQLite 等场景仅靠 create_all 建新表，不做 DDL 迁移
        return

    with bind.begin() as conn:
        grind_passes_exists = bool(
            conn.execute(
                text(
                    "SELECT COUNT(*) FROM information_schema.tables "
                    "WHERE table_schema = DATABASE() AND table_name = 'grind_passes'"
                )
            ).scalar()
        )
        if not grind_passes_exists:
            return

        if not _has_column(conn, "grind_passes", "ended_at"):
            # duration_min 先回填再补列，避免 NOT NULL 默认值影响旧版本库
            conn.execute(text("ALTER TABLE grind_passes ADD COLUMN ended_at DATETIME NULL"))

        try:
            _ensure_grind_passes_open_constraint(conn)
        except Exception as exc:  # noqa: BLE001
            # 多 worker 并发启动时，另一个进程可能已完成 DDL；下一次启动会跳过。
            # 其余原因（如历史脏数据导致建索引失败）打印出来便于排查，不阻塞启动。
            print(f"[migrate] grind_passes constraint skipped: {exc}")
