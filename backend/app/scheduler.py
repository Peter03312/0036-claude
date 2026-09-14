"""套印编排完整搜索引擎。

决策
----
1. 印台刮印次序 π（满足前驱、湿碰湿链首尾相邻、固定位置）；
2. 烘台闪干次序 σ（闪干层在唯一烘台上的互斥次序）。

对每一对 (π, σ) 分两阶段：

阶段一（最早时刻）——刮印与闪干起点构成差分约束系统 x_v - x_u ≥ c，用
队列式 Bellman-Ford（SPFA）求分量最早可行时刻，出现正环即该次序无解。
覆盖：同机次序链、前驱刮印先结束、闪干开始不早于刮印结束、湿碰湿首尾相接
（等式一正一反两条边）、复涂窗口的最短/最长等待（最长等待等价为对闪干
起点的下界）。

设备可用时段（左闭右开）是析取约束（落入若干时段之一）：当某操作按当前
最早时刻落不进所在资源的任何时段，就把它锚到能容纳它的下一时段起点
（抬高下界），再增量做最长路。锚定单调、只增不减，有限轮内收敛或判死。
推迟操作只会把后继顶得更晚、不会缓解任何 ≥ 约束，因此"选最早容纳时段"
不损失最优性。

阶段二（最晚闪干）——刮印固定为阶段一的最早时刻，在"闪干结束 ≤ 最小
makespan"上限下沿烘台次序反向传播上界并最晚落位，把每个闪干排到分量最晚。
每段窗口等待 ps_s − fe_f 随 fs_f 增大而减小，故分量最晚同时最小化等待和。

目标按字典序：(最晚结束时刻, 窗口等待总和, 刮印编号序列, 刮印起点序列,
闪干起点序列)。
"""
from __future__ import annotations

import bisect
import collections
import itertools
from dataclasses import dataclass

from .models import Layer, ScheduleInput, ScheduleSolution, LayerTiming

INF = float("inf")
EPS = 1e-9


@dataclass(frozen=True)
class Fix:
    layer_id: int
    position: int  # 从 1 起


def _earliest_fit(windows, starts, lb: float, dur: float):
    """在左闭右开时段集合中，找 ≥ lb 且 [t, t+dur) 完全落入某时段的最早 t。

    windows 已按起点排序且互不重叠，starts 为各时段起点。先二分定位 lb 所在
    或之后的第一个时段，命中通常 O(log W)；容不下才顺序向后找。
    """
    i = bisect.bisect_right(starts, lb) - 1
    if i < 0:
        i = 0
    for j in range(i, len(windows)):
        start, end = windows[j]
        if end - start + EPS < dur:
            continue
        t = lb if lb > start else start
        if t + dur <= end + EPS:
            return t
        # lb 落在该时段内却放不下 -> 只能看更晚的时段。
    return None


class _MaxPath:
    """增量最长路（SPFA）。地面下界可逐轮抬升，只重算受影响的节点。

    正环通过"最长路径边数 ≥ 变量数"判定（无环路径至多 n-1 条边），出现即
    约束矛盾（不可行）。
    """

    def __init__(self, n_vars: int, edges):
        self.n = n_vars
        self.adj: list[list[tuple[int, float]]] = [[] for _ in range(n_vars)]
        for u, v, c in edges:
            self.adj[u].append((v, c))
        # 初始 d=0 即虚拟源点到每点权 0；先求一次完整最长路。
        self.d = [0.0] * n_vars
        self._path_len = [0] * n_vars
        self.feasible = self._relax_all()

    def _relax_all(self) -> bool:
        # 全节点作为虚拟源点的后继（路径长度 0 起步），等价于带权 0 的源边。
        path_len = [0] * self.n
        queue: collections.deque[int] = collections.deque(range(self.n))
        ok = self._run(queue, [True] * self.n, path_len)
        self._path_len = path_len
        return ok

    def _run(self, queue, in_queue, path_len):
        """一次 SPFA 传播；路径边数 > n 判正环。返回 False 表示正环。

        path_len[v] 是当前支撑 d[v] 的最长路径含多少条边；一个无环路径至多
        n-1 条边，超过即说明绕了正环。比"入队次数"判据更可靠（DAG 多路径时
        同一节点也可能被反复入队）。
        """
        d, adj, n = self.d, self.adj, self.n
        while queue:
            u = queue.popleft()
            in_queue[u] = False
            du = d[u]
            for v, c in adj[u]:
                cand = du + c
                if cand > d[v] + EPS:
                    d[v] = cand
                    path_len[v] = path_len[u] + 1
                    if path_len[v] >= n:
                        return False  # 正环
                    if not in_queue[v]:
                        queue.append(v)
                        in_queue[v] = True
        return True

    def raise_ground(self, raises: dict[int, float]) -> bool:
        """抬升若干地面下界并增量传播；返回 False 表示出现正环。"""
        queue: collections.deque[int] = collections.deque()
        in_queue = [False] * self.n
        # 地面抬升不增加路径边数：沿用各点当前路径长度计数。
        path_len = getattr(self, "_path_len", [0] * self.n)
        for v, j in raises.items():
            if j > self.d[v] + EPS:
                self.d[v] = j
                queue.append(v)
                in_queue[v] = True
        if not queue:
            return True
        ok = self._run(queue, in_queue, path_len)
        self._path_len = path_len
        return ok


@dataclass
class _Prepared:
    layers: list[Layer]
    index: dict[int, int]
    press_windows: list[tuple[float, float]]
    oven_windows: list[tuple[float, float]]
    press_starts: list[float]
    oven_starts: list[float]
    group_next: dict[int, int]
    group_prev: dict[int, int]
    group_of: dict[int, str]
    window_pairs: list[tuple[int, int]]
    flash_idx: list[int]


def _prepare(inp: ScheduleInput) -> _Prepared:
    layers = list(inp.layers)
    index = {l.id: i for i, l in enumerate(layers)}
    pw = sorted((iv.start, iv.end) for iv in inp.press_windows)
    ow = sorted((iv.start, iv.end) for iv in inp.oven_windows)

    group_next: dict[int, int] = {}
    group_prev: dict[int, int] = {}
    group_of: dict[int, str] = {}
    groups: dict[str, list[Layer]] = {}
    for l in layers:
        if l.wet_group is not None:
            groups.setdefault(l.wet_group, []).append(l)
            group_of[index[l.id]] = l.wet_group
    for members in groups.values():
        mids = {m.id for m in members}
        for m in members:
            gi = index[m.id]
            for p in m.predecessors:
                if p in mids:
                    group_prev[gi] = index[p]
                    group_next[index[p]] = gi

    window_pairs: list[tuple[int, int]] = []
    for l in layers:
        if l.window_successor is not None and l.flash:
            window_pairs.append((index[l.id], index[l.window_successor]))

    flash_idx = [i for i, l in enumerate(layers) if l.flash]
    return _Prepared(
        layers=layers,
        index=index,
        press_windows=pw,
        oven_windows=ow,
        press_starts=[w[0] for w in pw],
        oven_starts=[w[0] for w in ow],
        group_next=group_next,
        group_prev=group_prev,
        group_of=group_of,
        window_pairs=window_pairs,
        flash_idx=flash_idx,
    )


def _enum_print_orders(prep: _Prepared, fixes: dict[int, int]):
    """枚举满足结构约束的刮印次序（下标序列）。fixes: 下标 -> 从 1 起位置。"""
    n = len(prep.layers)
    preds_of: list[list[int]] = [[] for _ in range(n)]
    for i, l in enumerate(prep.layers):
        for p in l.predecessors:
            preds_of[i].append(prep.index[p])
    for f, s in prep.window_pairs:  # 窗口后继刮印时闪干必须已结束
        preds_of[s].append(f)
    fixed_at: dict[int, int] = {pos - 1: li for li, pos in fixes.items()}

    def candidates(used: list[bool], partial: list[int]) -> list[int]:
        k = len(partial)
        forced = None
        if partial:
            nxt = prep.group_next.get(partial[-1])
            if nxt is not None and not used[nxt]:
                forced = nxt
        if k in fixed_at:
            fid = fixed_at[k]
            if used[fid]:
                return []
            if forced is not None and fid != forced:
                return []
            if not all(used[p] for p in preds_of[fid]):
                return []
            gp = prep.group_prev.get(fid)
            if gp is not None and (not partial or partial[-1] != gp):
                return []
            return [fid]
        if forced is not None:
            if not all(used[p] for p in preds_of[forced]):
                return []
            gp = prep.group_prev.get(forced)
            if gp is not None and partial[-1] != gp:
                return []
            return [forced]
        cands: list[int] = []
        for i in range(n):
            if used[i] or i in fixes:
                continue
            if not all(used[p] for p in preds_of[i]):
                continue
            gp = prep.group_prev.get(i)
            if gp is not None and (not partial or partial[-1] != gp):
                continue
            cands.append(i)
        return cands

    used = [False] * n
    partial: list[int] = []

    def dfs():
        if len(partial) == n:
            yield list(partial)
            return
        for c in candidates(used, partial):
            used[c] = True
            partial.append(c)
            yield from dfs()
            partial.pop()
            used[c] = False

    yield from dfs()


def _build_edges(prep: _Prepared, pi, sigma, relax_windows, relax_wet):
    """构造 ≥ 型差分约束边 (u, v, c) 表示 x_v ≥ x_u + c。"""
    layers = prep.layers
    PS = lambda i: 2 * i
    FS = lambda i: 2 * i + 1
    ge: list[tuple[int, int, float]] = []

    def add_ge(u, v, c):
        ge.append((u, v, c))

    for a, b in zip(pi, pi[1:]):
        add_ge(PS(a), PS(b), layers[a].duration)
    for a, b in zip(sigma, sigma[1:]):
        add_ge(FS(a), FS(b), layers[a].flash_duration)
    for i, l in enumerate(layers):
        for p in l.predecessors:
            pj = prep.index[p]
            add_ge(PS(pj), PS(i), layers[pj].duration)
    for i in prep.flash_idx:
        # 闪干开始不得早于刮印结束（fs_i ≥ ps_i + dur_i）；具体何时在烘台
        # 上排由第二阶段"最晚闪干"决定。
        add_ge(PS(i), FS(i), layers[i].duration)
    for a, b in prep.group_next.items():
        add_ge(PS(a), PS(b), layers[a].duration)
        if not relax_wet:
            add_ge(PS(b), PS(a), -layers[a].duration)
    if not relax_windows:
        for f, s in prep.window_pairs:
            fd = layers[f].flash_duration
            add_ge(FS(f), PS(s), fd + layers[f].wait_min)
            add_ge(PS(s), FS(f), -(fd + layers[f].wait_max))
    return ge


def _solve_order(prep: _Prepared, pi, sigma, relax_windows: bool, relax_wet: bool):
    """给定 π、σ 求最优时间解；不可行返回 None。

    系统全部为 ≥ 型差分约束，Bellman-Ford 最长路给出分量意义上最早的可行点。
    设备时段是析取（落入若干时段之一）：当操作按当前最早时刻落不进任何时段，
    就只能被推到下一时段起点（取最早的那个窗口——推迟只会把后继顶得更晚，
    不会缓解任何约束，故最早窗口选择最优）。锚定是单调的，反复传播至不动点。

    复涂窗口的"最长等待"等价为对闪干起点的下界
    fs_f ≥ ps_s - fd_f - wait_max，因此同样由最长路处理：贪心把闪干排在最早
    会超出窗口时，最长路自动把闪干推迟到窗口闭合处——这正是逐层最早排死、
    换序可解的关键机理。

    返回 (makespan, waitsum, earliest_d)。
    """
    layers = prep.layers
    n = len(layers)
    V = 2 * n
    PS = lambda i: 2 * i
    FS = lambda i: 2 * i + 1
    ge = _build_edges(prep, pi, sigma, relax_windows, relax_wet)
    solver = _MaxPath(V, ge)  # 邻接表只建一次，后续增量传播。
    if not solver.feasible:
        return None  # 初始约束即含正环（如零等待窗口被前驱链顶破）。

    resource_ops = [
        (PS(i), prep.press_windows, prep.press_starts, layers[i].duration)
        for i in pi
    ] + [
        (FS(i), prep.oven_windows, prep.oven_starts, layers[i].flash_duration)
        for i in sigma
    ]

    # 落位锚定：每轮把落不进时段的操作抬到下一时段起点，增量传播到不动点。
    max_rounds = V * (len(prep.press_windows) + len(prep.oven_windows) + 1) + 2
    d = solver.d
    for _ in range(max_rounds):
        raises: dict[int, float] = {}
        for var, windows, starts, dur in resource_ops:
            t = _earliest_fit(windows, starts, d[var], dur)
            if t is None:
                return None  # 任何时段都容纳不下
            if t > d[var] + EPS:
                raises[var] = t
        if not raises:
            break
        if not solver.raise_ground(raises):
            return None  # 正环：约束矛盾
        d = solver.d
    else:
        return None

    # 最终复核：操作确实在某时段内。
    for var, windows, starts, dur in resource_ops:
        t = _earliest_fit(windows, starts, d[var], dur)
        if t is None or abs(t - d[var]) > 1e-7:
            return None

    # 最小 makespan：最早解中所有操作（含最早闪干）的最晚结束。第二阶段把
    # 闪干延后时不得超过它，否则会增大第一目标。
    press_makespan = max(d[PS(i)] + layers[i].duration for i in range(n))
    makespan_T = press_makespan
    for fi in prep.flash_idx:
        makespan_T = max(makespan_T, d[FS(fi)] + layers[fi].flash_duration)

    # 第二阶段：刮印固定为最早时刻，在 fs+fd ≤ T* 下把各闪干排到分量最晚，
    # 第二阶段：先最小化窗口等待和，再让按 pi 排列的闪干起点序列字典序最小。
    opt = _optimize_flashes(prep, sigma, pi, d, makespan_T, relax_windows)
    if opt is None:
        return None
    fs, waitsum = opt

    # 用最晚闪干覆盖最早解中的 FS 分量（刮印分量不变）。
    out = list(d)
    for fi in prep.flash_idx:
        out[FS(fi)] = fs[fi]
    return makespan_T, waitsum, out


def _latest_fit(windows, starts, ub: float, lb: float, dur: float):
    """找起点满足 lb ≤ t ≤ ub、且 [t, t+dur) 完整落入某时段的最晚 t；无则 None。

    窗口互不重叠且按起点排序。ub 是**起点**上界（结束上界已由调用方换算）。
    """
    # 只看 start ≤ ub 的时段，从最晚时段向前找；同段内最晚点为 min(ub, end-dur)。
    i = bisect.bisect_right(starts, ub + EPS)
    for j in range(i - 1, -1, -1):
        start, end = windows[j]
        if end - start + EPS < dur:
            continue
        t = min(ub, end - dur)
        if t + EPS >= start and t >= lb - EPS and t <= ub + EPS:
            return t
    return None


def _flash_bounds(prep, sigma, earliest_d, makespan_T, relax_windows):
    """各闪干在固定刮印时刻下的静态上下界。

    下界 lo：不早于本层刮印结束。
    上界 hi：闪干结束不超过最小 makespan；窗口闪干还要保证后继等待 ≥ wait_min。
    一个后继可能同时是多个闪干层的窗口后继（多窗口），此时后继起点必须落在
    所有窗口的交集，下界取最严（max）、上界也取各窗口最严（min）。
    """
    layers = prep.layers
    PS = lambda i: 2 * i
    lo = {fi: earliest_d[PS(fi)] + layers[fi].duration for fi in sigma}
    hi = {fi: makespan_T - layers[fi].flash_duration for fi in sigma}
    if not relax_windows:
        for f, s in prep.window_pairs:
            hi[f] = min(
                hi[f],
                earliest_d[PS(s)] - layers[f].flash_duration - layers[f].wait_min,
            )
    return lo, hi


def _flash_latest_feasible(prep, sigma, lo, hi, fixed, relax_windows, earliest_d):
    """固定部分闪干后，求可达到"窗口等待和最大"的完整闪干排法。

    fixed：{闪干下标: 已锁定起点}。未锁定者按烘台次序 sigma 反复传播上下界，
    再从后向前锚到烘台时段内的最晚起点，直到不动点。每个窗口等待
    ps_s-(fs_f+fd_f) 对 fs_f 的系数为 +1，故把未锁定闪干排到分量最晚即最大化
    可达等待和（用于检验在固定若干起点后能否仍达到 W*）。
    返回 (fs, waitsum)；不可行返回 None。
    """
    layers = prep.layers
    nf = len(sigma)
    PS = lambda i: 2 * i
    fd = {f: layers[f].flash_duration for f in sigma}

    lo_cur = {f: max(lo[f], fixed.get(f, -INF)) for f in sigma}
    hi_cur = {f: min(hi[f], fixed[f] if f in fixed else INF) for f in sigma}
    if any(hi_cur[f] + EPS < lo_cur[f] for f in sigma):
        return None

    max_rounds = nf * (len(prep.oven_windows) + 1) + 2
    for _ in range(max_rounds):
        # 烘台固定序链式约束 fs_{k+1} >= fs_k + fd_k，双向传播界。
        for _ in range(nf + 1):
            changed = False
            for k in range(1, nf):  # 前向抬高下界
                a, b = sigma[k - 1], sigma[k]
                cand = lo_cur[a] + fd[a]
                if cand > lo_cur[b] + EPS and b not in fixed:
                    lo_cur[b] = cand
                    changed = True
            for k in range(nf - 2, -1, -1):  # 反向压低上界
                a, b = sigma[k], sigma[k + 1]
                cand = hi_cur[b] - fd[a]
                if cand + EPS < hi_cur[a] and a not in fixed:
                    hi_cur[a] = cand
                    changed = True
            if any(hi_cur[f] + EPS < lo_cur[f] for f in sigma):
                return None
            if not changed:
                break

        # 固定点必须落在烘台时段内。
        for f in fixed:
            t = fixed[f]
            if not any(t >= a - 1e-7 and t + fd[f] <= b + 1e-7 for a, b in prep.oven_windows):
                return None

        # 从后向前：未锁定者取 [lo, cap] 内最晚落位点。
        placed: dict[int, float] = {}
        progressed = False
        for k in range(nf - 1, -1, -1):
            f = sigma[k]
            cap = hi_cur[f] if k + 1 == nf else min(hi_cur[f], placed[sigma[k + 1]] - fd[f])
            if f in fixed:
                t = fixed[f]
                if t > cap + EPS or t + EPS < lo_cur[f]:
                    return None
            else:
                t = _latest_fit(prep.oven_windows, prep.oven_starts, cap, lo_cur[f], fd[f])
                if t is None:
                    return None
                if t + EPS < hi_cur[f]:
                    hi_cur[f] = t
                    progressed = True
            placed[f] = t
        if not progressed:
            fs = placed
            break
    else:
        return None

    # 复核：紧接下界、落时段、烘台互斥（sigma 顺序）、不超 makespan。
    for k, f in enumerate(sigma):
        if fs[f] + EPS < lo[f]:
            return None
        if not any(fs[f] >= a - 1e-7 and fs[f] + fd[f] <= b + 1e-7 for a, b in prep.oven_windows):
            return None
        if k > 0:
            prev = sigma[k - 1]
            if fs[f] + 1e-7 < fs[prev] + fd[prev]:
                return None

    waitsum = 0.0
    if not relax_windows:
        for f, s in prep.window_pairs:
            wait = earliest_d[PS(s)] - (fs[f] + fd[f])
            if wait < layers[f].wait_min - 1e-7 or wait > layers[f].wait_max + 1e-7:
                return None
            waitsum += wait
    return fs, waitsum


def _snap_to_oven(prep, t, dur):
    """对齐到 >= t 且能完整放下 dur 的最早烘台时段起点。"""
    return _earliest_fit(prep.oven_windows, prep.oven_starts, t, dur)


def _optimize_flashes(prep, sigma, pi, earliest_d, makespan_T, relax_windows):
    """第二阶段：刮印固定为最早时刻，在不改变最小 makespan 的前提下：

      1) 先把窗口等待总和压到最小 W*；
      2) 再在所有达到 W* 的排法中，取"按刮印序列 pi 排列的闪干起点序列"
         字典序最小者（闪干不无故拖晚；无窗口闪干自然尽早）。

    返回 (fs, waitsum) 或 None。
    """
    layers = prep.layers
    nf = len(sigma)
    if nf == 0:
        return {}, 0.0

    lo, hi = _flash_bounds(prep, sigma, earliest_d, makespan_T, relax_windows)
    if any(hi[f] + EPS < lo[f] for f in sigma):
        return None
    fd = {f: layers[f].flash_duration for f in sigma}

    # 第一步：全部尽量晚，得到可达到的最小等待和 W* 与各闪干最晚值。
    latest = _flash_latest_feasible(prep, sigma, lo, hi, {}, relax_windows, earliest_d)
    if latest is None:
        return None
    fs_latest, w_star = latest
    if relax_windows:
        return fs_latest, w_star  # 诊断放开窗口时无需字典序细化。

    # 第二步：按刮印序列 pi 中出现的先后，逐闪干锁定到不牺牲 W* 的最小起点。
    # 可行起点是离散的：烘台时段端点、"不早于刮印结束"的下界、以及复涂窗口
    # 派生的拐点。把这些事件点作为候选，二分找能在固定后仍达到 W* 的最小者。
    PS = lambda i: 2 * i
    flash_in_pi = [i for i in pi if i in set(sigma)]
    fixed: dict[int, float] = {}

    def keeps(f: int, t: float):
        """固定 fs_f=t 后，等待和能否仍达到最小 W* 且固定点被尊重。

        W* 是最小等待和；oracle 给出固定后能达到的最小等待，必须不大于 W*。
        """
        if t + EPS < lo[f] or t > hi[f] + EPS:
            return False
        trial = dict(fixed)
        trial[f] = t
        res = _flash_latest_feasible(
            prep, sigma, lo, hi, trial, relax_windows, earliest_d
        )
        return (
            res is not None
            and abs(res[0][f] - t) <= 1e-7
            and res[1] <= w_star + 1e-7
        )

    # 全局事件点：所有操作时长组合出的潜在拐点。
    durations = {0.0}
    for l in layers:
        durations.add(l.duration)
        if l.flash:
            durations.add(l.flash_duration)
    events: set[float] = {0.0}
    for a, b in prep.oven_windows:
        events.add(a)
        events.add(b)
    for _ in range(5):
        grown = set(events)
        for t in events:
            for dd in durations:
                grown.add(round(t + dd, 9))
                grown.add(round(t - dd, 9))
        if grown <= events:
            break
        events |= grown

    for f in flash_in_pi:
        # 该闪干相关的窗口拐点：后继起点 - fd - wait（wait 取上下限）。
        extra = {lo[f], hi[f], fs_latest[f]}
        lf = layers[f]
        if lf.window_successor is not None:
            ps_s = earliest_d[PS(prep.index[lf.window_successor])]
            extra.add(ps_s - fd[f] - lf.wait_min)
            extra.add(ps_s - fd[f] - lf.wait_max)
        cands = sorted(
            t
            for t in (events | extra)
            if lo[f] - 1e-7 <= t <= fs_latest[f] + 1e-7
        )
        chosen = None
        left, right = 0, len(cands) - 1
        while left <= right:
            m = (left + right) // 2
            if keeps(f, cands[m]):
                chosen, right = cands[m], m - 1
            else:
                left = m + 1
        fixed[f] = chosen if chosen is not None else fs_latest[f]

    final = _flash_latest_feasible(
        prep, sigma, lo, hi, fixed, relax_windows, earliest_d
    )
    if final is None or final[1] < w_star - 1e-7:
        return None
    fs, waitsum = final
    return fs, waitsum
def _normalize_fixes(prep: _Prepared, fixes: list[Fix]):
    out: dict[int, int] = {}
    used_pos: set[int] = set()
    n = len(prep.layers)
    for fx in fixes:
        if fx.layer_id not in prep.index or not 1 <= fx.position <= n:
            return None
        if fx.position in used_pos:
            return None
        i = prep.index[fx.layer_id]
        if i in out:
            return None
        out[i] = fx.position
        used_pos.add(fx.position)
    return out


def search(
    inp: ScheduleInput,
    fixes: list[Fix],
    relax_windows: bool = False,
    relax_wet: bool = False,
) -> ScheduleSolution | None:
    """完整搜索；无解返回 None。"""
    prep = _prepare(inp)
    fix_map = _normalize_fixes(prep, fixes)
    if fix_map is None:
        return None

    best = None
    for pi in _enum_print_orders(prep, fix_map):
        for sigma in itertools.permutations(prep.flash_idx):
            sigma = list(sigma)
            solved = _solve_order(prep, pi, sigma, relax_windows, relax_wet)
            if solved is None:
                continue
            makespan, waitsum, d = solved
            seq_ids = tuple(prep.layers[i].id for i in pi)
            press_starts = tuple(round(d[2 * i], 9) for i in pi)
            flash_starts = tuple(
                round(d[2 * i + 1], 9) if prep.layers[i].flash else None for i in pi
            )
            key = (
                round(makespan, 9),
                round(waitsum, 9),
                seq_ids,
                press_starts,
                flash_starts,
            )
            if best is None or key < best[0]:
                best = (key, (pi, d, makespan, waitsum))

    if best is None:
        return None
    _key, (pi, d, makespan, waitsum) = best
    return _build_solution(prep, pi, d, makespan, waitsum)


def _build_solution(prep: _Prepared, pi, d, makespan, waitsum) -> ScheduleSolution:
    layers = prep.layers
    wait_of: dict[int, float] = {}
    for f, s in prep.window_pairs:
        fe = d[2 * f + 1] + layers[f].flash_duration
        wait_of[f] = d[2 * s] - fe

    timings: dict[int, LayerTiming] = {}
    for i, l in enumerate(layers):
        ps = d[2 * i]
        pe = ps + l.duration
        fs = d[2 * i + 1] if l.flash else None
        fe = fs + l.flash_duration if fs is not None else None
        wwait = wait_of.get(i)
        slack = (
            (l.wait_max - wwait)
            if wwait is not None and l.window_successor is not None
            else None
        )
        timings[l.id] = LayerTiming(
            layer_id=l.id,
            press_start=round(ps, 9),
            press_end=round(pe, 9),
            flash_start=round(fs, 9) if fs is not None else None,
            flash_end=round(fe, 9) if fe is not None else None,
            window_slack=round(slack, 9) if slack is not None else None,
            window_wait=round(wwait, 9) if wwait is not None else None,
        )

    return ScheduleSolution(
        feasible=True,
        makespan=round(makespan, 9),
        window_wait_sum=round(waitsum, 9),
        print_sequence=[layers[i].id for i in pi],
        press_starts=[round(d[2 * i], 9) for i in pi],
        flash_starts=[
            round(d[2 * i + 1], 9) if layers[i].flash else None for i in pi
        ],
        timings=timings,
    )
