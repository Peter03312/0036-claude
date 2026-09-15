"""输入解析与静态校验。

解析图层 JSON 与设备可用时段 CSV，定位错误（文件/行/字段），
并在真正进入搜索前捕捉结构性冲突。
"""
from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass

from .models import Conflict, Interval, Layer, ScheduleInput


class InputError(Exception):
    """携带可定位信息的输入错误。"""

    def __init__(self, message: str, location: str | None = None):
        super().__init__(message)
        self.message = message
        self.location = location

    def render(self) -> str:
        return f"{self.location}: {self.message}" if self.location else self.message


def parse_layers_json(raw: bytes | str) -> list[Layer]:
    """解析图层 JSON。

    接受顶层为数组，或 {"layers": [...]} 的对象。
    """
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8-sig")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InputError(
            f"JSON 解析失败：{exc.msg}",
            location=f"layers.json 第 {exc.lineno} 行第 {exc.colno} 列",
        ) from exc

    if isinstance(data, dict) and "layers" in data:
        data = data["layers"]
    if not isinstance(data, list):
        raise InputError("图层 JSON 顶层必须是数组或含 layers 数组的对象", "layers.json")

    layers: list[Layer] = []
    seen: set[int] = set()
    for i, item in enumerate(data):
        loc = f"layers.json[{i}]"
        if not isinstance(item, dict):
            raise InputError("每个图层必须是对象", loc)
        try:
            layer = Layer.model_validate(item)
        except Exception as exc:  # pydantic.ValidationError
            raise InputError(_first_error(exc), loc) from exc
        if layer.id in seen:
            raise InputError(f"图层编号 {layer.id} 重复", loc)
        seen.add(layer.id)
        layers.append(layer)

    if not layers:
        raise InputError("图层列表为空", "layers.json")
    return layers


def _first_error(exc: Exception) -> str:
    """从 pydantic 校验错误中提取首条可读信息。"""
    errors = getattr(exc, "errors", lambda: [])()
    if not errors:
        return str(exc)
    err = errors[0]
    loc = ".".join(str(x) for x in err.get("loc", ()))
    return f"{loc}: {err.get('msg', '校验失败')}" if loc else err.get("msg", "校验失败")


def parse_windows_csv(raw: bytes | str, source: str) -> list[Interval]:
    """解析设备可用时段 CSV，表头须含 start,end（支持设备列但单设备忽略）。"""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8-sig")
    text = io.StringIO(raw)
    reader = csv.DictReader(text)
    if reader.fieldnames is None:
        raise InputError("CSV 为空或缺少表头", source)
    headers = [h.strip().lower() for h in reader.fieldnames]
    if "start" not in headers or "end" not in headers:
        raise InputError(
            f"CSV 表头必须包含 start 与 end 列，实际为：{reader.fieldnames}", source
        )

    intervals: list[Interval] = []
    for line_no, row in enumerate(reader, start=2):  # 表头是第 1 行
        loc = f"{source} 第 {line_no} 行"
        cleaned = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        try:
            start = float(cleaned["start"])
            end = float(cleaned["end"])
        except (KeyError, ValueError):
            raise InputError("start/end 必须是数值", loc)
        except TypeError:
            raise InputError("start/end 必须是数值", loc)
        if start < 0 or end < 0:
            raise InputError("时间不能为负", loc)
        if not end > start:
            raise InputError(f"时段须满足 end({end}) > start({start})", loc)
        intervals.append(Interval(start=start, end=end))

    if not intervals:
        raise InputError("没有任何可用时段", source)

    intervals.sort(key=lambda iv: iv.start)
    for a, b in zip(intervals, intervals[1:]):
        if b.start < a.end:
            raise InputError(
                f"时段重叠或乱序：[{a.start}, {a.end}) 与 [{b.start}, {b.end})",
                source,
            )
    return intervals


@dataclass
class StaticReport:
    conflicts: list[Conflict]


def static_validate(inp: ScheduleInput) -> StaticReport:
    """结构性校验：引用、环、窗口设置、湿碰湿组结构。"""
    conflicts: list[Conflict] = []
    by_id = {l.id: l for l in inp.layers}
    ids = set(by_id)

    def add(ctype: str, message: str, layers: list[int]) -> None:
        conflicts.append(Conflict(type=ctype, message=message, layers=layers))

    # 空作业：没有任何图层无法排程。
    if not inp.layers:
        add("EMPTY_LAYERS", "图层列表为空：请至少上传一个图层后再排程。", [])
        return StaticReport(conflicts=conflicts)

    # 引用完整性
    for l in inp.layers:
        for p in l.predecessors:
            if p not in ids:
                add(
                    "UNKNOWN_PREDECESSOR",
                    f"图层 {l.id} 的前驱 {p} 不存在",
                    [l.id],
                )
            if p == l.id:
                add("SELF_DEPENDENCY", f"图层 {l.id} 不能以自身为前驱", [l.id])
        ws = l.window_successor
        if ws is not None:
            if not l.flash:
                add(
                    "WINDOW_ON_NON_FLASH",
                    f"图层 {l.id} 未闪干却设置了窗口后继 {ws}；仅闪干层可设窗口后继",
                    [l.id, ws] if ws in ids else [l.id],
                )
            if ws not in ids:
                add("UNKNOWN_WINDOW_SUCCESSOR", f"图层 {l.id} 的窗口后继 {ws} 不存在", [l.id])
            elif ws == l.id:
                add("SELF_DEPENDENCY", f"图层 {l.id} 的窗口后继不能是自身", [l.id])
        if l.flash and l.flash_duration <= 0:
            add("BAD_FLASH_DURATION", f"闪干层 {l.id} 的闪干时长必须为正", [l.id])
        if not l.flash and l.flash_duration > 0:
            add(
                "FLASH_DURATION_WITHOUT_FLASH",
                f"图层 {l.id} 标记不闪干却给了闪干时长",
                [l.id],
            )
        if ws is not None:
            if l.wait_min > l.wait_max:
                add(
                    "BAD_WINDOW_BOUNDS",
                    f"图层 {l.id} 的等待下限 {l.wait_min} 大于上限 {l.wait_max}",
                    [l.id],
                )

    # 前驱环（窗口后继在时间上反向前驱，不参与环检测）。
    cycle = _find_cycle(by_id)
    if cycle:
        add(
            "DEPENDENCY_CYCLE",
            "依赖关系存在环：" + " -> ".join(str(x) for x in cycle),
            cycle,
        )

    # 一个图层可以同时是多个闪干层的窗口后继：其后继起点必须同时落入各窗口
    # 闭区间，交集是否非空（连同设备时段、互斥等）由完整搜索在运行期判定。

    # 湿碰湿组：同组层必须以组内前驱串成链（允许首节点无前驱）。
    groups: dict[str, list[Layer]] = {}
    for l in inp.layers:
        if l.wet_group is not None:
            groups.setdefault(l.wet_group, []).append(l)
    for gname, members in groups.items():
        mids = {m.id for m in members}
        incoming: dict[int, list[int]] = {m.id: [] for m in members}
        for m in members:
            for p in m.predecessors:
                if p in mids:
                    incoming[m.id].append(p)
        roots = [mid for mid, ps in incoming.items() if len(ps) == 0]
        if len(members) == 1:
            add(
                "WET_GROUP_SINGLE",
                f"湿碰湿组 {gname!r} 只有图层 {members[0].id}，无法首尾相接",
                [members[0].id],
            )
            continue
        if len(roots) != 1:
            add(
                "WET_GROUP_NOT_CHAIN",
                f"湿碰湿组 {gname!r} 必须有且仅有一个组内起点，实际起点为 {roots}",
                sorted(mids),
            )
            continue
        for mid, ps in incoming.items():
            if len(ps) > 1:
                add(
                    "WET_GROUP_NOT_CHAIN",
                    f"湿碰湿组 {gname!r} 中图层 {mid} 有多个组内前驱 {ps}，不构成链",
                    sorted(mids),
                )
                break
        else:
            # 检查从唯一根能否遍历全组（防分叉/孤岛）
            chain = _walk_chain(roots[0], members)
            if chain is None or set(chain) != mids:
                add(
                    "WET_GROUP_NOT_CHAIN",
                    f"湿碰湿组 {gname!r} 无法构成覆盖全组的链",
                    sorted(mids),
                )

    return StaticReport(conflicts=conflicts)


def _walk_chain(root: int, members: list[Layer]) -> list[int] | None:
    by_id = {m.id: m for m in members}
    mids = set(by_id)
    nexts: dict[int, int] = {}
    for m in members:
        for p in m.predecessors:
            if p in mids:
                if p in nexts:
                    return None  # 分叉
                nexts[p] = m.id
    chain = [root]
    cur = root
    while cur in nexts:
        cur = nexts[cur]
        chain.append(cur)
    return chain


def _find_cycle(by_id: dict[int, Layer]) -> list[int] | None:
    """在前驱边与窗口后继边上做 DFS 找环，返回环上编号。"""
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {i: WHITE for i in by_id}
    stack: list[int] = []

    def edges_of(lid: int) -> list[int]:
        # 仅前驱边构成偏序；窗口后继表示时间反向约束，不计入环。
        return [p for p in by_id[lid].predecessors if p in by_id]

    def dfs(u: int) -> list[int] | None:
        color[u] = GRAY
        stack.append(u)
        for v in edges_of(u):
            if color[v] == GRAY:
                idx = stack.index(v)
                return stack[idx:] + [v]
            if color[v] == WHITE:
                found = dfs(v)
                if found:
                    return found
        stack.pop()
        color[u] = BLACK
        return None

    for i in by_id:
        if color[i] == WHITE:
            found = dfs(i)
            if found:
                return found
    return None
