"""阀门井室接口：维护阀门，覆盖安排启闭、确认正常/卡涩、停用阀门等动作。"""
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
from app.services.valve import ValveService

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
    """台账统计口径：与 /api/overview 中 valve 模块的待确认数保持一致。"""
    return service.stats()


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出阀门井室清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "valve", "total": total, "items": items}


@router.post("/batch-actions", response_model=BatchActionResult)
def run_batch_action(payload: BatchActionPayload) -> BatchActionResult:
    """批量对阀门执行同一动作：逐条独立处理，单条失败不影响其他条目。

    返回每条记录的成功/失败原因；同一批中重复出现的阀门只执行一次。
    """
    result = service.run_batch(payload.action, payload.ids)
    return BatchActionResult(**result)


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
def run_action(entry_id: int, payload: dict[str, Any]) -> ActionResult:
    """对单条阀门执行安排启闭、确认正常/卡涩、停用阀门。

    兼容两种提交方式：直接发 {"action": "..."}（页面使用的格式），
    或统一载荷 {"values": {"action": "..."}}。
    业务不满足前置条件时返回 HTTP 200 且 ok=false，并在 message 中逐条说明原因。
    """
    action = str(
        payload.get("action")
        or (payload.get("values") or {}).get("action")
        or ""
    ).strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
