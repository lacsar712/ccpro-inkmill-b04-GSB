from datetime import datetime

from flask import jsonify


def error(message: str, status: int = 400):
    return jsonify({"message": message}), status


def parse_datetime(value: str) -> datetime | None:
    """严格解析时间字符串，失败返回 None（不静默兜底）。"""
    value = (value or "").strip()
    if not value:
        return None
    for fmt in (
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(value.replace("Z", "")[:26], fmt)
        except ValueError:
            continue
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt
    except ValueError:
        return None


def normalize_datetime(value: str) -> datetime:
    parsed = parse_datetime(value)
    return parsed if parsed is not None else datetime.now()


def dt_to_json(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%d %H:%M:%S")
