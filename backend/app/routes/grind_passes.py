from datetime import datetime
from decimal import Decimal

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app.models.grind_pass import GrindPass
from app.models.mill import Mill
from app.serializers import grind_pass_json
from app.utils import error

bp = Blueprint("grind_passes", __name__, url_prefix="/api/grind-passes")


def _parse_dt(raw) -> tuple[datetime | None, str | None]:
    """严格解析时间，失败由调用方返回 400，不静默取当前时间。"""
    text_value = str(raw or "").strip()
    if not text_value:
        return None, "不能为空"
    try:
        parsed = datetime.fromisoformat(text_value.replace("Z", "+00:00"))
    except ValueError:
        return None, "格式无效，应为 YYYY-MM-DDTHH:MM"
    if parsed.tzinfo is not None:
        # 库内按本地无时区时间存储，比较前统一去掉时区
        parsed = parsed.replace(tzinfo=None)
    return parsed, None


def _validate_open_fields(body: dict, db, mill_id: int) -> tuple[str | None, int]:
    """新建“进行中遍次”的公共校验。不做 passNo 查重。

    返回 (错误消息, HTTP 状态码)；通过时为 (None, 0)。
    """
    mill = db.get(Mill, mill_id)
    if not mill:
        return "研磨机不存在", 400
    if mill.status != "grinding":
        return "该研磨机当前不是研磨状态(grinding)，不能新建遍次", 409

    if (
        db.query(GrindPass.id)
        .filter(GrindPass.mill_id == mill_id, GrindPass.ended_at.is_(None))
        .first()
    ):
        return "该研磨机已有进行中的遍次，请先结束后再新建", 409

    try:
        pass_no = int(body.get("passNo") or 0)
    except (TypeError, ValueError):
        return "遍次编号必须为 ≥ 1 的整数", 400
    if pass_no < 1:
        return "遍次编号必须 ≥ 1", 400

    duration_raw = body.get("durationMin", 0)
    try:
        duration_min = float(duration_raw)
    except (TypeError, ValueError):
        return "研磨时长(分钟)必须为数字", 400
    if duration_min != 0:
        return "新建的遍次处于进行中，durationMin 须为 0；时长在结束时由服务端计算", 400

    if not str(body.get("mediaType", "")).strip():
        return "研磨介质不能为空", 400

    if not str(body.get("operatorName", "")).strip():
        return "操作员不能为空", 400

    return None, 0


@bp.get("")
@jwt_required()
def list_passes():
    db = SessionLocal()
    try:
        rows = (
            db.query(GrindPass)
            .order_by(GrindPass.started_at.desc(), GrindPass.id.desc())
            .all()
        )
        return jsonify([grind_pass_json(r) for r in rows])
    finally:
        db.close()


@bp.post("")
@jwt_required()
def create_pass():
    body = request.get_json(silent=True) or {}

    try:
        mill_id = int(body.get("millId") or 0)
    except (TypeError, ValueError):
        return error("请选择研磨机", 400)
    if mill_id <= 0:
        return error("请选择研磨机", 400)

    started_at, dt_err = _parse_dt(body.get("startedAt"))
    if dt_err:
        return error(f"开始时间{dt_err}", 400)

    db = SessionLocal()
    try:
        err, status = _validate_open_fields(body, db, mill_id)
        if err:
            return error(err, status)

        row = GrindPass(
            mill_id=mill_id,
            started_at=started_at,
            ended_at=None,
            pass_no=int(body["passNo"]),
            duration_min=Decimal("0"),
            media_type=str(body["mediaType"]).strip(),
            operator_name=str(body["operatorName"]).strip(),
        )
        db.add(row)
        try:
            db.commit()
        except IntegrityError:
            # 并发下数据库层 uq_grind_pass_open_mill 兜底
            db.rollback()
            return error("该研磨机已有进行中的遍次，请先结束后再新建", 409)
        db.refresh(row)
        return jsonify(grind_pass_json(row)), 201
    finally:
        db.close()


@bp.post("/<int:item_id>/end")
@jwt_required()
def end_pass(item_id: int):
    body = request.get_json(silent=True) or {}

    ended_at, dt_err = _parse_dt(body.get("endedAt"))
    if dt_err:
        return error(f"结束时间{dt_err}", 400)

    client_duration = None
    if body.get("durationMin") is not None and str(body.get("durationMin")).strip() != "":
        try:
            client_duration = float(body["durationMin"])
        except (TypeError, ValueError):
            return error("研磨时长(分钟)必须为数字", 400)
        if client_duration < 0:
            return error("研磨时长(分钟)不能为负数", 400)

    db = SessionLocal()
    try:
        row = db.get(GrindPass, item_id)
        if not row:
            return error("研磨遍次不存在", 404)
        if row.ended_at is not None:
            return error("该遍次已结束，不能重复结束", 409)

        if ended_at <= row.started_at:
            return error("结束时间必须晚于开始时间", 400)

        delta_seconds = (ended_at - row.started_at).total_seconds()
        computed_min = (Decimal(str(delta_seconds)) / Decimal("60")).quantize(
            Decimal("0.01")
        )
        if computed_min <= 0:
            return error("结束时间必须晚于开始时间", 400)

        if client_duration is not None:
            if abs(Decimal(str(client_duration)) - computed_min) > Decimal("1"):
                return error(
                    "提交的时长与按起止时间计算的结果相差超过 1 分钟，未写入",
                    400,
                )

        row.ended_at = ended_at
        row.duration_min = computed_min
        db.commit()
        db.refresh(row)
        return jsonify(grind_pass_json(row))
    finally:
        db.close()


@bp.put("/<int:item_id>")
@jwt_required()
def update_pass(item_id: int):
    body = request.get_json(silent=True) or {}

    try:
        mill_id = int(body.get("millId") or 0)
    except (TypeError, ValueError):
        return error("请选择研磨机", 400)
    if mill_id <= 0:
        return error("请选择研磨机", 400)

    started_at, dt_err = _parse_dt(body.get("startedAt"))
    if dt_err:
        return error(f"开始时间{dt_err}", 400)

    db = SessionLocal()
    try:
        row = db.get(GrindPass, item_id)
        if not row:
            return error("研磨遍次不存在", 404)
        if row.ended_at is not None:
            return error("已结束的遍次不可修改", 409)

        # 换机台时按新机台规则校验；留在原机台时排除自身的进行中记录
        target_open = (
            db.query(GrindPass)
            .filter(
                GrindPass.mill_id == mill_id,
                GrindPass.ended_at.is_(None),
                GrindPass.id != item_id,
            )
            .first()
        )
        mill = db.get(Mill, mill_id)
        if not mill:
            return error("研磨机不存在", 400)
        if mill.status != "grinding":
            return error("该研磨机当前不是研磨状态(grinding)，不能挂接遍次", 409)
        if target_open:
            return error("该研磨机已有进行中的遍次，请先结束后再新建", 409)

        try:
            pass_no = int(body.get("passNo") or 0)
        except (TypeError, ValueError):
            return error("遍次编号必须为 ≥ 1 的整数", 400)
        if pass_no < 1:
            return error("遍次编号必须 ≥ 1", 400)
        if not str(body.get("mediaType", "")).strip():
            return error("研磨介质不能为空", 400)
        if not str(body.get("operatorName", "")).strip():
            return error("操作员不能为空", 400)

        row.mill_id = mill_id
        row.started_at = started_at
        row.pass_no = pass_no
        # 进行中遍次时长恒为 0，结束时才由服务端计算
        row.duration_min = Decimal("0")
        row.media_type = str(body["mediaType"]).strip()
        row.operator_name = str(body["operatorName"]).strip()
        db.commit()
        db.refresh(row)
        return jsonify(grind_pass_json(row))
    finally:
        db.close()


@bp.delete("/<int:item_id>")
@jwt_required()
def delete_pass(item_id: int):
    db = SessionLocal()
    try:
        row = db.get(GrindPass, item_id)
        if not row:
            return error("研磨遍次不存在", 404)
        if row.ended_at is not None:
            return error("已结束的遍次禁止删除", 409)
        db.delete(row)
        db.commit()
        return jsonify({"ok": True})
    finally:
        db.close()
