"""调度引擎单元测试：约束语义与字典序目标。"""
from __future__ import annotations

from app.models import Interval, Layer, ScheduleInput
from app.scheduler import Fix, search


def L(**kw):
    base = dict(
        predecessors=[], wet_group=None, flash=False, flash_duration=0,
        window_successor=None, wait_min=0, wait_max=0,
    )
    base.update(kw)
    return Layer(**base)


def mk(layers, pw=((0, 100),), ow=((0, 100),)):
    return ScheduleInput(
        layers=layers,
        press_windows=[Interval(start=a, end=b) for a, b in pw],
        oven_windows=[Interval(start=a, end=b) for a, b in ow],
    )


def test_half_open_window_boundary():
    # 刮印长 5 放入 [0,5)（右端点开区间）合法。
    inp = mk([L(id=1, duration=5)], pw=((0, 5),))
    sol = search(inp, [])
    assert sol is not None and sol.makespan == 5


def test_press_mutual_exclusion():
    inp = mk([L(id=1, duration=3), L(id=2, duration=4)])
    sol = search(inp, [])
    t = sol.timings
    # 两块刮印不得重叠（makespan = 7）。
    assert sol.makespan == 7
    assert t[1].press_end <= t[2].press_start or t[2].press_end <= t[1].press_start


def test_oven_mutual_exclusion():
    inp = mk([
        L(id=1, duration=2, flash=True, flash_duration=5),
        L(id=2, duration=2, flash=True, flash_duration=5),
    ])
    sol = search(inp, [])
    a, b = sol.timings[1], sol.timings[2]
    assert a.flash_end <= b.flash_start or b.flash_end <= a.flash_start


def test_predecessor_must_finish_first():
    inp = mk([
        L(id=1, duration=3),
        L(id=2, duration=2, predecessors=[1]),
    ])
    sol = search(inp, [])
    assert sol.print_sequence == [1, 2]
    assert sol.timings[2].press_start >= 3


def test_flash_starts_no_earlier_than_print_end():
    # 单层：闪干不得早于刮印结束；最小 makespan 下闪干紧接刮印。
    inp = mk([L(id=1, duration=3, flash=True, flash_duration=4)])
    sol = search(inp, [])
    t = sol.timings[1]
    assert t.flash_start >= t.press_end
    assert t.press_end == 3
    assert t.flash_end == t.flash_start + 4
    # 无其他约束时最小 makespan 让闪干紧接其后。
    assert t.flash_start == 3


def test_flash_can_be_delayed_on_oven():
    # 有窗口后继时，闪干可在烘台上延后以压到最小等待；闪干开始允许晚于
    # 刮印结束（只要求不早于）。
    inp = mk([
        L(id=1, duration=4, flash=True, flash_duration=6),
        L(id=2, duration=5, predecessors=[1]),
        L(id=3, duration=2, predecessors=[2]),
    ])
    sol = search(inp, [])
    t = sol.timings[1]
    assert t.flash_start >= t.press_end
    # 与印台刮印并行：闪干区间与刮印 2 时间重叠。
    assert t.flash_start < sol.timings[2].press_end
    assert sol.timings[2].press_start < t.flash_end


def test_recoat_window_closed_interval():
    # 等待恰为下限/上限均合法（闭区间）。
    inp = mk([
        L(id=1, duration=2, flash=True, flash_duration=2,
          window_successor=2, wait_min=1, wait_max=1),
        L(id=2, duration=2, predecessors=[1]),
    ])
    sol = search(inp, [])
    assert sol is not None
    assert sol.timings[1].window_wait == 1
    assert sol.timings[1].window_slack == 0


def test_window_wait_sum_minimized():
    # 最小 makespan=14 下两个次序等待和不同：[2,4,1,3] 等待 1，
    # [4,2,1,3] 等待 0。第二目标须选出后者（闪干在烘台上尽量晚排）。
    inp = mk([
        L(id=1, duration=2),
        L(id=2, duration=6, flash=True, flash_duration=2,
          window_successor=3, wait_min=0, wait_max=9),
        L(id=3, duration=3, predecessors=[1]),
        L(id=4, duration=3, flash=True, flash_duration=4),
    ], pw=((0, 100),), ow=((0, 100),))
    sol = search(inp, [])
    assert sol is not None
    assert sol.makespan == 14
    assert round(sol.window_wait_sum, 9) == 0
    assert sol.print_sequence == [4, 2, 1, 3]


def test_lexicographic_sequence_prefers_smaller_id():
    # 两层无前驱、等时长：两种次序 makespan 相同，取编号序列字典序小者 [1,2]。
    inp = mk([L(id=2, duration=3), L(id=1, duration=3)])
    sol = search(inp, [])
    assert sol.print_sequence == [1, 2]


def test_wet_group_no_idle_no_outsider():
    inp = mk([
        L(id=1, duration=3, wet_group="A"),
        L(id=2, duration=3, predecessors=[1], wet_group="A"),
        L(id=3, duration=2),
    ])
    # 所有可行解中，1、2 必须相邻且首尾相接（3 不得插入）。
    sol = search(inp, [])
    seq = sol.print_sequence
    assert abs(seq.index(1) - seq.index(2)) == 1
    t = sol.timings
    assert t[2].press_start == t[1].press_end


def test_wet_group_cannot_span_gap():
    inp = mk([
        L(id=1, duration=4, wet_group="A"),
        L(id=2, duration=4, predecessors=[1], wet_group="A"),
    ], pw=((0, 6), (10, 16)))
    assert search(inp, []) is None


def test_fixed_position_is_honored():
    inp = mk([
        L(id=1, duration=2, predecessors=[2]),
        L(id=2, duration=2),
        L(id=3, duration=2),
    ])
    sol = search(inp, [Fix(layer_id=3, position=1)])
    assert sol is not None and sol.print_sequence[0] == 3


def test_inconsistent_fix_returns_none():
    inp = mk([
        L(id=1, duration=2),
        L(id=2, duration=2, predecessors=[1]),
    ])
    assert search(inp, [Fix(layer_id=2, position=1)]) is None


def test_operation_must_lie_in_window():
    # 唯一时段容不下时长。
    inp = mk([L(id=1, duration=8)], pw=((0, 5),))
    assert search(inp, []) is None


def test_window_infeasible_device_gap():
    # 零等待窗口与两台时段错配：闪干在烘台 [0,10) 内无论怎么延后，都无法把
    # 后继刮印对齐到印台开放时刻（印台 [0,4) 后要等到 20）。
    inp = mk(
        [
            L(id=1, duration=3, flash=True, flash_duration=4,
              window_successor=2, wait_min=0, wait_max=0),
            L(id=2, duration=2, predecessors=[1]),
        ],
        pw=((0, 4), (20, 30)),
        ow=((0, 10),),
    )
    assert search(inp, []) is None
