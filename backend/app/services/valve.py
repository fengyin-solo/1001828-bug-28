"""阀门井室业务规则：状态流转、字段校验、逐条动作结果与统计口径都收在这里。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.store import store
from app.status_rules import ABNORMAL_STATUSES, PENDING_STATUSES

MODULE = "valve"
REQUIRED_FIELDS = ["阀门编号", "阀门类别", "所在管段"]
STATUS_ORDER = ["待启闭", "操作正常", "启闭卡涩", "已停用"]
PENDING_SET = PENDING_STATUSES[MODULE]  # 待启闭、启闭卡涩
ABNORMAL_SET = ABNORMAL_STATUSES[MODULE]  # 启闭卡涩、已停用

# 动作 -> 目标状态
ACTION_RULES = {"安排启闭": "操作正常", "确认正常": "操作正常", "停用阀门": "已停用"}
# 动作允许的前置状态：不在范围内就给出可读的失败原因
ACTION_PRECONDITIONS = {
    "安排启闭": frozenset({"待启闭", "启闭卡涩"}),
    "确认正常": frozenset({"启闭卡涩"}),
    "停用阀门": frozenset({"待启闭", "操作正常", "启闭卡涩"}),
}


def _stamp(entry: dict[str, Any], *, action: str, ok: bool, message: str) -> None:
    """把最近一次操作结果写到记录上，刷新后仍能看到哪一步没生效。"""
    entry["last_action"] = action
    entry["last_ok"] = ok
    entry["last_message"] = message
    entry["last_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


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
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"阀门 {entry_id} 不存在或已归档"
        message = self._apply(entry, action)
        if entry["last_ok"] is False:
            return None, message
        return entry, message

    def run_batch(self, action: str, entry_ids: list[int]) -> list[dict[str, Any]]:
        """批量动作逐条独立执行：同一条井室只处理一次，单条失败不影响其它条目。"""
        results: list[dict[str, Any]] = []
        seen: set[int] = set()
        for entry_id in entry_ids:
            if entry_id in seen:
                continue
            seen.add(entry_id)
            entry = store.find(MODULE, entry_id)
            if entry is None:
                results.append({
                    "id": entry_id,
                    "ok": False,
                    "message": f"阀门 {entry_id} 不存在或已归档",
                    "entry": None,
                })
                continue
            message = self._apply(entry, action)
            results.append({
                "id": entry_id,
                "ok": bool(entry["last_ok"]),
                "message": message,
                "entry": entry if entry["last_ok"] else None,
            })
        return results

    def stats(self) -> dict[str, int]:
        """台账统计：待确认数与运营概览同一口径，都按状态推导。"""
        rows = store.rows(MODULE)
        return {
            "total": len(rows),
            "abnormal": sum(1 for row in rows if str(row.get("status")) in ABNORMAL_SET),
            "pending": sum(1 for row in rows if str(row.get("status")) in PENDING_SET),
        }

    def _apply(self, entry: dict[str, Any], action: str) -> str:
        """在原记录上执行动作并落结果；任何一步不满足都写明原因，记录保持原状态。"""
        entry_id = entry.get("id")
        code = entry.get("阀门编号") or f"#{entry_id}"
        if action not in ACTION_RULES:
            message = f"阀门 {code}：动作「{action}」不属于阀门井室可执行范围"
            _stamp(entry, action=action, ok=False, message=message)
            return message
        current = str(entry.get("status"))
        allowed = ACTION_PRECONDITIONS[action]
        if current not in allowed:
            message = f"阀门 {code} 当前为「{current}」，不允许{action}（仅{'、'.join(sorted(allowed))}状态可操作）"
            _stamp(entry, action=action, ok=False, message=message)
            return message
        target = ACTION_RULES[action]
        entry["status"] = target
        entry["pending"] = target in PENDING_SET
        entry["abnormal"] = target in ABNORMAL_SET
        message = f"阀门 {code} 已{action}"
        _stamp(entry, action=action, ok=True, message=message)
        return message
