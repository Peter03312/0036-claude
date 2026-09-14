"""真正无解时的冲突诊断。

通过在搜索中逐类放开约束，定位是哪类约束杀死了所有排法：

* 放开设备时段约束后可行  -> DEVICE_WINDOW / 设备时段相关冲突；
* 只放开湿碰湿"无空闲"等式（保留同序链）后可行 -> WET_GROUP_SPLIT；
* 只放开复涂窗口上下限后可行 -> WINDOW_INFEASIBLE；
* 都放开仍无解（互斥+前驱+闪干顺序的核心矛盾）-> NO_FEASIBLE_SCHEDULE。
"""
from __future__ import annotations

from .models import Conflict, ScheduleInput
from .scheduler import Fix, _prepare, search


def diagnose(inp: ScheduleInput, fixes: list[Fix]) -> list[Conflict]:
    layers = list(inp.layers)

    # 1) 放开设备时段：只留一个极大时段。
    from .models import Interval

    relaxed_inp = ScheduleInput(
        layers=layers,
        press_windows=[Interval(start=0.0, end=1e12)],
        oven_windows=[Interval(start=0.0, end=1e12)],
    )
    if search(relaxed_inp, fixes) is not None:
        return _device_conflicts(inp, fixes)

    # 2) 在无限设备条件下放开湿碰湿"无空闲"。
    if search(relaxed_inp, fixes, relax_wet=True) is not None:
        return _wet_conflicts(inp, fixes)

    # 3) 在无限设备条件下放开复涂窗口。
    if search(relaxed_inp, fixes, relax_windows=True) is not None:
        return _window_conflicts(inp, fixes)

    # 4) 核心矛盾：互斥 + 前驱 + 闪干先后本身无解（一般是固定位置所致）。
    involved = sorted(f.layer_id for f in fixes)
    return [
        Conflict(
            type="NO_FEASIBLE_SCHEDULE",
            message=(
                "即使忽略设备时段、湿碰湿无空闲与复涂窗口，前驱关系与"
                "单印台/单烘台互斥下仍不存在可行排程"
                + (f"（涉及固定位置图层 {involved}）" if involved else "")
            ),
            layers=involved,
        )
    ]


def _device_conflicts(inp: ScheduleInput, fixes: list[Fix]) -> list[Conflict]:
    """区分：操作装不进任何单个时段，还是时段间隙切断了湿碰湿链。"""
    conflicts: list[Conflict] = []
    by_id = {l.id: l for l in inp.layers}

    # 单操作容量：是否存在容纳得下该时长的时段。
    bad_press = [
        l.id
        for l in inp.layers
        if not any(e - s >= l.duration for s, e in ((w.start, w.end) for w in inp.press_windows))
    ]
    if bad_press:
        conflicts.append(
            Conflict(
                type="PRESS_WINDOW_TOO_SHORT",
                message="以下图层的刮印时长超过印台任一可用时段，无法安排",
                layers=sorted(bad_press),
            )
        )
    bad_oven = [
        l.id
        for l in inp.layers
        if l.flash
        and not any(w.end - w.start >= l.flash_duration for w in inp.oven_windows)
    ]
    if bad_oven:
        conflicts.append(
            Conflict(
                type="OVEN_WINDOW_TOO_SHORT",
                message="以下闪干层的闪干时长超过烘台任一可用时段，无法安排",
                layers=sorted(bad_oven),
            )
        )
    if conflicts:
        return conflicts

    # 间隙切断湿碰湿链：找最长连续可用印台跨度仍放不下的链段。
    prep = _prepare(inp)
    seen_chains: set[int] = set()
    for i, group in prep.group_of.items():
        if i in prep.group_prev:
            continue
        # 沿链收集
        chain = [i]
        cur = i
        while cur in prep.group_next:
            cur = prep.group_next[cur]
            chain.append(cur)
        total = sum(prep.layers[j].duration for j in chain)
        if not any(w.end - w.start >= total for w in inp.press_windows):
            ids = [prep.layers[j].id for j in chain]
            key = tuple(ids)
            if key not in seen_chains:
                seen_chains.add(key)
                conflicts.append(
                    Conflict(
                        type="WET_GROUP_SPLIT",
                        message=(
                            f"湿碰湿组 {group!r}（图层 {ids}）必须首尾相接共需 "
                            f"{total:g}，但印台没有任何一个连续可用时段容纳得下，"
                            "组被时段间隙切断"
                        ),
                        layers=ids,
                    )
                )
    if conflicts:
        return conflicts

    # 闪干与刮印跨设备配合不上（印台/烘台时段不重叠）等通用设备冲突。
    return [
        Conflict(
            type="DEVICE_WINDOW_INFEASIBLE",
            message=(
                "所有操作虽各自能放进单个时段，但受印台/烘台可用时段及相互先后"
                "约束，不存在全部落位的排程；请放宽可用时段后重试"
            ),
            layers=sorted(by_id),
        )
    ]


def _wet_conflicts(inp: ScheduleInput, fixes: list[Fix]) -> list[Conflict]:
    prep = _prepare(inp)
    groups: dict[str, list[int]] = {}
    for i, g in prep.group_of.items():
        groups.setdefault(g, []).append(prep.layers[i].id)
    layers_out: list[int] = []
    for ids in groups.values():
        layers_out.extend(sorted(ids))
    return [
        Conflict(
            type="WET_GROUP_SPLIT",
            message=(
                "湿碰湿组要求同组层在印台首尾相接、无空闲且不插入组外刮印；"
                "放开该约束后才有可行排程，说明设备时段间隙或资源占用迫使链中断"
            ),
            layers=sorted(layers_out),
        )
    ]


def _window_conflicts(inp: ScheduleInput, fixes: list[Fix]) -> list[Conflict]:
    ids = sorted(
        l.id for l in inp.layers if l.window_successor is not None and l.flash
    )
    return [
        Conflict(
            type="WINDOW_INFEASIBLE",
            message=(
                "复涂窗口要求后继刮印始于闪干结束后 [最短等待, 最长等待] 的闭区间；"
                "放开窗口上下限后才有可行排程，请调整这些闪干层的等待上下限或可用时段"
            ),
            layers=ids,
        )
    ]
