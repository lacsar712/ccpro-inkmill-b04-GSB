from datetime import datetime
from decimal import Decimal

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

from app.database import SessionLocal
from app.models.grind_pass import GrindPass
from app.models.mill import Mill
from app.serializers import grind_pass_json
from app.utils import error, normalize_datetime, parse_datetime

bp = Blueprint("grind_passes", __name__, url_prefix="/api/grind-passes")


def _validate_fields(body: dict) -> str | None:
    if int(body.get("millId") or 0) <= 0:
        return "请选择研磨机"

    if not str(body.get("startedAt", "")).strip():
        return "开始时间不能为空"

    if int(body.get("passNo") or 0) < 1:
        return "遍次编号必须 ≥ 1"

    try:
        duration_min = float(body.get("durationMin") or 0)
    except (TypeError, ValueError):
        return "研磨时长(分钟)格式无效"
    if duration_min < 0:
        return "研磨时长(分钟)不能为负数"

    if not str(body.get("mediaType", "")).strip():
        return "研磨介质不能为空"

    if not str(body.get("operatorName", "")).strip():
        return "操作员不能为空"

    return None


def _open_pass_of(db, mill_id: int, exclude_id: int | None = None) -> GrindPass | None:
    q = db.query(GrindPass).filter(
        GrindPass.mill_id == mill_id, GrindPass.ended_at.is_(None)
    )
    if exclude_id is not None:
        q = q.filter(GrindPass.id != exclude_id)
    return q.first()


def _check_mill_accept_open_pass(db, mill_id: int, exclude_id: int | None = None):
    """校验研磨机可挂接一条进行中遍次，返回 (mill, error_response)。"""
    mill = db.get(Mill, mill_id)
    if not mill:
        return None, error("研磨机不存在", 400)
    if mill.status != "grinding":
        return None, error("该研磨机当前不是研磨中状态，不能新建研磨遍次", 409)
    if _open_pass_of(db, mill_id, exclude_id):
        return None, error("该研磨机已有进行中的研磨遍次，请先结束", 409)
    return mill, None


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
    err = _validate_fields(body)
    if err:
        return error(err, 400)

    db = SessionLocal()
    try:
        mill, resp = _check_mill_accept_open_pass(db, int(body["millId"]))
        if resp:
            return resp

        row = GrindPass(
            mill_id=mill.id,
            started_at=normalize_datetime(str(body["startedAt"])),
            ended_at=None,
            pass_no=int(body["passNo"]),
            duration_min=Decimal(str(body.get("durationMin") or 0)),
            media_type=str(body["mediaType"]).strip(),
            operator_name=str(body["operatorName"]).strip(),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return jsonify(grind_pass_json(row)), 201
    finally:
        db.close()


@bp.put("/<int:item_id>")
@jwt_required()
def update_pass(item_id: int):
    body = request.get_json(silent=True) or {}
    err = _validate_fields(body)
    if err:
        return error(err, 400)

    db = SessionLocal()
    try:
        row = db.get(GrindPass, item_id)
        if not row:
            return error("研磨遍次不存在", 404)
        if row.ended_at is not None:
            return error("已结束的研磨遍次禁止修改", 409)

        new_mill_id = int(body["millId"])
        if new_mill_id != row.mill_id:
            mill, resp = _check_mill_accept_open_pass(db, new_mill_id, exclude_id=row.id)
            if resp:
                return resp
            row.mill_id = mill.id

        row.started_at = normalize_datetime(str(body["startedAt"]))
        row.pass_no = int(body["passNo"])
        row.duration_min = Decimal(str(body.get("durationMin") or 0))
        row.media_type = str(body["mediaType"]).strip()
        row.operator_name = str(body["operatorName"]).strip()
        db.commit()
        db.refresh(row)
        return jsonify(grind_pass_json(row))
    finally:
        db.close()


@bp.post("/<int:item_id>/end")
@jwt_required()
def end_pass(item_id: int):
    body = request.get_json(silent=True) or {}

    db = SessionLocal()
    try:
        row = db.get(GrindPass, item_id)
        if not row:
            return error("研磨遍次不存在", 404)
        if row.ended_at is not None:
            return error("该研磨遍次已结束，不能重复结束", 409)

        ended_raw = str(body.get("endedAt", "")).strip()
        if ended_raw:
            ended_at = parse_datetime(ended_raw)
            if ended_at is None:
                return error("结束时间格式无效", 400)
        else:
            ended_at = datetime.now()

        if ended_at <= row.started_at:
            return error("结束时间必须晚于开始时间", 400)

        computed_min = (ended_at - row.started_at).total_seconds() / 60
        duration_min = round(computed_min, 2)
        if duration_min <= 0:
            return error("研磨时长必须大于 0 分钟", 400)

        if body.get("durationMin") is not None:
            try:
                provided_min = float(body.get("durationMin"))
            except (TypeError, ValueError):
                return error("研磨时长(分钟)格式无效", 400)
            if abs(provided_min - computed_min) > 1:
                return error("请求时长与起止时间计算的时长相差超过 1 分钟", 400)

        # 时长一律以服务端按起止时间计算的值为准
        row.ended_at = ended_at
        row.duration_min = Decimal(str(duration_min))
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
            return error("已结束的研磨遍次禁止删除", 409)
        db.delete(row)
        db.commit()
        return jsonify({"ok": True})
    finally:
        db.close()
