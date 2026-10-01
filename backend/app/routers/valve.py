"""阀门井室接口：维护阀门，覆盖安排启闭、确认正常、停用阀门等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import (
    ActionResult,
    BatchActionPayload,
    BatchActionResult,
    EntryPayload,
    PageResult,
)
from app.services.valve import ACTION_RULES, ValveService

router = APIRouter(prefix="/api/valve", tags=["阀门井室"])

service = ValveService()

LIST_FIELDS = ["阀门编号", "阀门类别", "所在管段", "公称直径", "操作方向", "上次启闭日", "责任人员", "阀门状态"]
STATUSES = ["待启闭", "操作正常", "启闭卡涩", "已停用"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按阀门编号检索"),
    status: str | None = Query(default=None, description="待启闭、操作正常、启闭卡涩、已停用"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按阀门编号与状态过滤阀门井室列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/stats")
def get_stats() -> dict[str, int]:
    """台账统计：在册、启闭卡涩、待确认，待确认口径与运营概览一致。"""
    return service.stats()


@router.post("/batch-actions", response_model=BatchActionResult)
def run_batch_action(payload: BatchActionPayload) -> BatchActionResult:
    """对多条阀门执行同一动作：逐条独立处理，已成功的立即生效，失败的逐条给出原因。

    同一批里重复出现的阀门只处理一次；整批请求即使部分失败也返回 200，
    由 items 逐条说明结果，前端可只对失败条目重试。
    """
    action = (payload.action or "").strip()
    if action not in ACTION_RULES:
        raise HTTPException(status_code=400, detail=f"动作「{action}」不属于阀门井室可执行范围")
    if not payload.entry_ids:
        raise HTTPException(status_code=400, detail="未选择任何阀门，请先勾选要操作的记录")
    items = service.run_batch(action, payload.entry_ids)
    success_count = sum(1 for item in items if item["ok"])
    failure_count = len(items) - success_count
    if failure_count:
        summary = f"批量{action}完成：成功 {success_count} 条，失败 {failure_count} 条，可对失败条目重试"
    else:
        summary = f"批量{action}完成：{success_count} 条均已生效"
    return BatchActionResult(
        ok=failure_count == 0,
        action=action,
        total=len(items),
        success_count=success_count,
        failure_count=failure_count,
        message=summary,
        items=items,
    )


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出阀门井室清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "valve", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条阀门明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"阀门 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条阀门，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="阀门已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条阀门执行安排启闭、确认正常、停用阀门；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
