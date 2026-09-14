"""内置示例。

时间单位一致即可（示例按分钟）。设备区间左闭右开。
"""
from __future__ import annotations


def _layer(
    id, duration, predecessors=None, wet_group=None, flash=False, flash_duration=0,
    window_successor=None, wait_min=0, wait_max=0,
):
    return {
        "id": id,
        "duration": duration,
        "predecessors": predecessors or [],
        "wet_group": wet_group,
        "flash": flash,
        "flash_duration": flash_duration,
        "window_successor": window_successor,
        "wait_min": wait_min,
        "wait_max": wait_max,
    }


def greedy_miss_sample() -> dict:
    """贪心逐层排最早会错失窗口、换序才可行的样例。

    * 印台时段 [0,10)、[10,19)，烘台时段 [0,6)、[6,46)；
    * 图层 1：刮印 3、闪干 3，窗口后继 3，等待 [0,1]；
    * 图层 2：刮印 9、闪干 3，无前驱；
    * 图层 3：刮印 3，前驱 1、2。

    按编号逐层排最早：1@[0,3) 后 2 必须 [3,12)，跨印台间隙只能挪到
    [10,19)，于是 3 最早 19 开始却装不进 [10,19)，且闪干 1 无论如何都无法
    把 3 的起点同时压进窗口 [fe1, fe1+1] 与 ≥19——排死。
    换序 [2,1,3]：2@[0,9)，1@[10,13)（跳过间隙），闪干 [13,16)，
    3@16（等待 0，窗口余量 1），最晚结束 19。
    """
    return {
        "layers": [
            _layer(1, 3, flash=True, flash_duration=3, window_successor=3, wait_min=0, wait_max=1),
            _layer(2, 9, flash=True, flash_duration=3),
            _layer(3, 3, predecessors=[1, 2]),
        ],
        "press_windows": [{"start": 0, "end": 10}, {"start": 10, "end": 19}],
        "oven_windows": [{"start": 0, "end": 6}, {"start": 6, "end": 46}],
    }


def parallel_sample() -> dict:
    """两设备合法并行：烘台闪干与印台下一块刮印时间重叠。"""
    return {
        "layers": [
            _layer(1, 4, flash=True, flash_duration=6),
            _layer(2, 5, predecessors=[1]),
            _layer(3, 2, predecessors=[2]),
        ],
        # 1 刮印 [0,4)、闪干 [4,10)；2 在印台 [4,9) 与闪干并行；3 [9,11)。
        "press_windows": [{"start": 0, "end": 20}],
        "oven_windows": [{"start": 0, "end": 20}],
    }


def wet_split_sample() -> dict:
    """时段间隙切断湿碰湿组（无解）。

    组 A：1->2->3 必须在同一印台首尾相接，共需 12；印台每个连续时段只有 6。
    """
    return {
        "layers": [
            _layer(1, 4, wet_group="A"),
            _layer(2, 4, predecessors=[1], wet_group="A"),
            _layer(3, 4, predecessors=[2], wet_group="A"),
        ],
        "press_windows": [{"start": 0, "end": 6}, {"start": 10, "end": 16}],
        "oven_windows": [{"start": 0, "end": 30}],
    }


def infeasible_window_sample() -> dict:
    """真正无解：零等待复涂窗口与两台设备时段错配。

    * 印台时段 [0,4)、[20,30)，烘台仅 [0,10)；
    * 图层 1：刮印 3、闪干 4，窗口后继 2 要求等待恰好 0；
    * 图层 2：刮印 2，前驱 1。

    图层 1 只能在印台第一时段刮印（第二时段刮印则闪干超出烘台 10 关闭），
    闪干结束 fe∈[7,10)；零等待要求图层 2 恰在 fe 开始，却正落在印台间隙
    [4,20)，等到 20 又违反零等待——闪干在烘台 [0,10) 内无论怎么排都无法把
    后继起点对齐到印台开放时刻。彻底无解（DEVICE_WINDOW_INFEASIBLE）。
    """
    return {
        "layers": [
            _layer(
                1, 3, flash=True, flash_duration=4,
                window_successor=2, wait_min=0, wait_max=0,
            ),
            _layer(2, 2, predecessors=[1]),
        ],
        "press_windows": [{"start": 0, "end": 4}, {"start": 20, "end": 30}],
        "oven_windows": [{"start": 0, "end": 10}],
    }
