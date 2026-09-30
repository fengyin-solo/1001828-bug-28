"""阀门井室业务规则：状态流转、字段校验、筛选口径与批量确认都收在这里。

状态机：
  待启闭 ──安排启闭/确认正常──▶ 操作正常
  待启闭 ──确认卡涩──▶ 启闭卡涩 ──确认正常（处理后重试）──▶ 操作正常
  待启闭/操作正常/启闭卡涩 ──停用阀门──▶ 已停用（终态）

设计约定：
- 每个动作都带前置状态校验，不满足时返回可读原因，而不是静默不改。
- pending 表示「待确认」（仅待启闭），abnormal 表示「启闭卡涩」；
  台账统计与运营概览都按同一口径计算，两处数字必须一致。
- 批量执行逐条独立落库：中间某条失败不回滚已成功的记录，刷新后仍可看到进度。
"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "valve"
REQUIRED_FIELDS = ["阀门编号", "阀门类别", "所在管段"]
STATUS_ORDER = ["待启闭", "操作正常", "启闭卡涩", "已停用"]
PENDING_STATUS = "待启闭"
ABNORMAL_STATUS = "启闭卡涩"
TERMINAL_STATUS = "已停用"

# 动作 -> (允许的源状态, 目标状态)
ACTION_RULES: dict[str, tuple[tuple[str, ...], str]] = {
    "安排启闭": (("待启闭",), "操作正常"),
    "确认正常": (("待启闭", "启闭卡涩"), "操作正常"),
    "确认卡涩": (("待启闭",), "启闭卡涩"),
    "停用阀门": (("待启闭", "操作正常", "启闭卡涩"), "已停用"),
}
NEGATIVE_ACTIONS = ["停用阀门"]


def _sync_flags(entry: dict[str, Any]) -> None:
    """按状态同步待确认/异常标记，保证列表、统计、概览口径一致。"""
    status = str(entry.get("status"))
    entry["pending"] = status == PENDING_STATUS
    entry["abnormal"] = status == ABNORMAL_STATUS


class ValveService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("阀门编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def stats(self) -> dict[str, int]:
        """台账统计：在册数、启闭卡涩数、待确认数；口径与 /api/overview 完全一致。"""
        rows = store.rows(MODULE)
        return {
            "total": len(rows),
            "pending": sum(1 for row in rows if row.get("status") == PENDING_STATUS),
            "abnormal": sum(1 for row in rows if row.get("status") == ABNORMAL_STATUS),
        }

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        _sync_flags(entry)
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        """执行单条动作。成功时改动立即落库；失败时原样返回并说明原因。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"阀门 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action or '空'}」不属于阀门井室可执行范围"
        sources, target = ACTION_RULES[action]
        current = str(entry.get("status"))
        if current not in sources:
            allowed = "、".join(sources)
            return None, f"阀门「{entry.get('阀门编号', entry_id)}」当前为「{current}」，动作「{action}」仅适用于{allowed}状态"
        entry["status"] = target
        _sync_flags(entry)
        return entry, f"阀门「{entry.get('阀门编号', entry_id)}」已{action}"

    def run_batch(
        self,
        action: str,
        entry_ids: list[Any],
    ) -> dict[str, Any]:
        """批量执行同一动作，逐条独立处理。

        - 同一批里重复出现的阀门只算一次（按首次出现顺序去重）；
        - 任意一条失败都不影响其余条目，也不回滚已成功的记录；
        - 返回每条的成功/失败原因，前端可针对失败项原动作重试。
        """
        if action not in ACTION_RULES:
            return {
                "ok": False,
                "action": action,
                "total": 0,
                "succeeded": 0,
                "failed": 0,
                "message": f"动作「{action or '空'}」不属于阀门井室可执行范围",
                "results": [],
            }

        unique_ids: list[int] = []
        seen: set[int] = set()
        for raw in entry_ids:
            try:
                entry_id = int(raw)
            except (TypeError, ValueError):
                continue
            if entry_id not in seen:
                seen.add(entry_id)
                unique_ids.append(entry_id)

        results: list[dict[str, Any]] = []
        succeeded = 0
        for entry_id in unique_ids:
            entry, message = self.run_action(entry_id, action)
            ok = entry is not None
            succeeded += int(ok)
            results.append({
                "id": entry_id,
                "label": str(entry.get("阀门编号") if entry else f"阀门 {entry_id}"),
                "ok": ok,
                "message": message,
                "entry": entry,
            })

        failed = len(results) - succeeded
        if not results:
            message = "没有可执行的阀门，请先在列表中勾选"
        elif failed == 0:
            message = f"全部 {succeeded} 条阀门「{action}」成功"
        elif succeeded == 0:
            message = f"{failed} 条阀门「{action}」均失败，请按逐条原因处理后重试"
        else:
            message = f"成功 {succeeded} 条，失败 {failed} 条；已成功的记录即时生效，失败项可重试"
        return {
            "ok": failed == 0,
            "action": action,
            "total": len(results),
            "succeeded": succeeded,
            "failed": failed,
            "message": message,
            "results": results,
        }
