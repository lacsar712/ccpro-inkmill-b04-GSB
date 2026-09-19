#!/bin/sh
set -e

PORT="${PORT:-9200}"

echo "Waiting for MySQL..."
python - <<'PY'
import os, time
from sqlalchemy import create_engine, text
from app.config import settings

url = settings.database_url
for i in range(60):
    try:
        engine = create_engine(url)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("Database is ready.")
        break
    except Exception as e:
        print(f"DB not ready ({i+1}/60): {e}")
        time.sleep(2)
else:
    raise SystemExit("Database not ready after retries")
PY

echo "Creating tables..."
python -c "from app.database import Base, engine; from app import models; Base.metadata.create_all(bind=engine)"

echo "Applying schema upgrades..."
python - <<'PY'
# create_all 不会给已存在的表补列，这里做幂等升级：
# 1. grind_passes 补 ended_at（空 = 进行中）
# 2. 历史数据按时长回填 ended_at，避免旧记录被误判为进行中
from sqlalchemy import text
from app.database import engine

with engine.begin() as conn:
    cols = {r[0] for r in conn.execute(text("SHOW COLUMNS FROM grind_passes"))}
    if "ended_at" not in cols:
        conn.execute(text("ALTER TABLE grind_passes ADD COLUMN ended_at DATETIME NULL"))
        conn.execute(text(
            "UPDATE grind_passes "
            "SET ended_at = DATE_ADD(started_at, INTERVAL CAST(duration_min * 60 AS SIGNED) SECOND) "
            "WHERE ended_at IS NULL AND duration_min > 0"
        ))
        print("Upgraded grind_passes: added ended_at and backfilled history.")
PY

if [ "${SEED_ON_START}" = "true" ] || [ "${SEED_ON_START}" = "1" ]; then
  echo "Seeding data..."
  python -c "from app.seed import seed; seed()"
fi

echo "Starting gunicorn on :${PORT}..."
exec gunicorn wsgi:app --bind "0.0.0.0:${PORT}" --workers 2 --threads 4 --timeout 120
