"""各业务模块状态口径：待确认（pending）与异常（abnormal）一律按状态推导。

概览看板与各模块台账都从这里取口径，避免同一批数据两边数对不上。
"""
from __future__ import annotations

PENDING_STATUSES: dict[str, frozenset[str]] = {
    "pipe": frozenset({"待移交", "重点观测"}),
    "manhole": frozenset({"待清掏", "井盖缺失"}),
    "valve": frozenset({"待启闭", "启闭卡涩"}),
    "pumpstation": frozenset({"待接管", "减量运行"}),
    "patrol": frozenset({"待派发", "巡查中"}),
    "defect": frozenset({"待定级", "已定级"}),
    "cctv": frozenset({"待检测", "检测中"}),
    "repair": frozenset({"待开工", "施工中"}),
    "pressure": frozenset({"待采集", "压力越限"}),
    "flow": frozenset({"待采集", "流量异常"}),
    "leak": frozenset({"待排查", "排查中"}),
    "dredge": frozenset({"待安排", "清淤中"}),
    "material": frozenset({"正常可用", "临近不足"}),
    "equip": frozenset({"待保养", "可用"}),
    "traffic": frozenset({"待审批", "施工中"}),
    "complaint": frozenset({"待受理", "办理中"}),
    "fund": frozenset({"待审批", "已批复"}),
    "archive": frozenset({"待归档", "待补充"}),
}

ABNORMAL_STATUSES: dict[str, frozenset[str]] = {
    "pipe": frozenset({"重点观测"}),
    "manhole": frozenset({"井盖缺失"}),
    "valve": frozenset({"启闭卡涩", "已停用"}),
    "pumpstation": frozenset({"减量运行"}),
    "patrol": frozenset({"巡查中"}),
    "defect": frozenset({"已定级"}),
    "cctv": frozenset({"检测中"}),
    "repair": frozenset({"施工中"}),
    "pressure": frozenset({"压力越限"}),
    "flow": frozenset({"流量异常"}),
    "leak": frozenset({"排查中"}),
    "dredge": frozenset({"清淤中"}),
    "material": frozenset({"临近不足"}),
    "equip": frozenset({"待保养"}),
    "traffic": frozenset({"施工中"}),
    "complaint": frozenset({"办理中"}),
    "fund": frozenset({"已批复"}),
    "archive": frozenset({"待补充"}),
}


def is_pending(module: str, status: object) -> bool:
    """该状态是否仍需确认；未登记口径的模块按行上的 pending 标记兜底。"""
    rules = PENDING_STATUSES.get(module)
    if rules is None:
        return False
    return str(status) in rules


def is_abnormal(module: str, status: object) -> bool:
    rules = ABNORMAL_STATUSES.get(module)
    if rules is None:
        return False
    return str(status) in rules
