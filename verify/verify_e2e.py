"""Compose verify 服务内运行的端到端 HTTP 冒烟。

启动方需先在本机起好 uvicorn（127.0.0.1:8000）。覆盖五类验收：
贪心失窗但换序可行、两设备并行、间隙切断湿碰湿组、真正无解、采纳快照。
退出码非 0 即验收失败。
"""
from __future__ import annotations

import json
import sys
import urllib.request

BASE = "http://127.0.0.1:8000"


def post(path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as r:
        return json.load(r)


def check(cond: bool, msg: str) -> None:
    if not cond:
        print(f"❌ {msg}")
        sys.exit(1)
    print(f"    {msg}")


def main() -> None:
    # 1) 贪心逐层排最早排死、换序可行（内置示例同参数）。
    greedy = {
        "input": {
            "layers": [
                {"id": 1, "duration": 3, "predecessors": [], "wet_group": None,
                 "flash": True, "flash_duration": 3, "window_successor": 3,
                 "wait_min": 0, "wait_max": 1},
                {"id": 2, "duration": 9, "predecessors": [], "wet_group": None,
                 "flash": True, "flash_duration": 3, "window_successor": None,
                 "wait_min": 0, "wait_max": 0},
                {"id": 3, "duration": 3, "predecessors": [1, 2], "wet_group": None,
                 "flash": False, "flash_duration": 0, "window_successor": None,
                 "wait_min": 0, "wait_max": 0},
            ],
            "press_windows": [{"start": 0, "end": 10}, {"start": 10, "end": 19}],
            "oven_windows": [{"start": 0, "end": 6}, {"start": 6, "end": 46}],
        },
        "fix_positions": [],
    }
    sol = post("/api/schedule", greedy)
    check(sol["feasible"] and sol["print_sequence"] == [2, 1, 3],
          f"贪心失窗/换序可行：{sol.get('print_sequence')} makespan={sol.get('makespan')}")
    t1 = sol["timings"]["1"]
    check(t1["press_start"] == 10 and t1["flash_start"] == 13, "图层1落入第二时段")
    check(t1["window_wait"] == 0 and t1["window_slack"] == 1, "窗口等待0、余量1")

    forced = dict(greedy)
    forced["fix_positions"] = [
        {"layer_id": 1, "position": 1},
        {"layer_id": 2, "position": 2},
        {"layer_id": 3, "position": 3},
    ]
    bad = post("/api/schedule", forced)
    check(bad["feasible"] is False and bad["conflicts"], "贪心编号序排死并返回冲突")

    # 2) 两设备合法并行。
    parallel = {"input": {
        "layers": [
            {"id": 1, "duration": 4, "predecessors": [], "flash": True, "flash_duration": 6},
            {"id": 2, "duration": 5, "predecessors": [1], "flash": False},
            {"id": 3, "duration": 2, "predecessors": [2], "flash": False},
        ],
        "press_windows": [{"start": 0, "end": 20}],
        "oven_windows": [{"start": 0, "end": 20}],
    }, "fix_positions": []}
    ps = post("/api/schedule", parallel)["timings"]
    check(float(ps["1"]["flash_start"]) >= 4
          and float(ps["1"]["flash_start"]) < float(ps["2"]["press_end"])
          and float(ps["2"]["press_start"]) < float(ps["1"]["flash_end"]),
          f"两设备并行：闪干{ps['1']['flash_start']}-{ps['1']['flash_end']} "
          f"刮印2 {ps['2']['press_start']}-{ps['2']['press_end']}")

    # 3) 时段间隙切断湿碰湿组。
    wet = {"input": {
        "layers": [
            {"id": 1, "duration": 4, "predecessors": [], "wet_group": "A", "flash": False},
            {"id": 2, "duration": 4, "predecessors": [1], "wet_group": "A", "flash": False},
            {"id": 3, "duration": 4, "predecessors": [2], "wet_group": "A", "flash": False},
        ],
        "press_windows": [{"start": 0, "end": 6}, {"start": 10, "end": 16}],
        "oven_windows": [{"start": 0, "end": 30}],
    }, "fix_positions": []}
    wc = post("/api/schedule", wet)
    check(wc["feasible"] is False and wc["conflicts"][0]["type"] == "WET_GROUP_SPLIT",
          "间隙切断湿碰湿组：WET_GROUP_SPLIT")

    # 4) 真正无解：零等待窗口与两台时段错配。
    infeasible = {"input": {
        "layers": [
            {"id": 1, "duration": 3, "predecessors": [], "flash": True,
             "flash_duration": 4, "window_successor": 2, "wait_min": 0, "wait_max": 0},
            {"id": 2, "duration": 2, "predecessors": [1], "flash": False},
        ],
        "press_windows": [{"start": 0, "end": 4}, {"start": 20, "end": 30}],
        "oven_windows": [{"start": 0, "end": 10}],
    }, "fix_positions": []}
    ic = post("/api/schedule", infeasible)
    types = {c["type"] for c in ic["conflicts"]}
    check(ic["feasible"] is False and bool(types & {"WINDOW_INFEASIBLE", "DEVICE_WINDOW_INFEASIBLE"}),
          f"真正无解：{sorted(types)}")

    # 4b) 一个后继受两个合法窗口约束、有共同时间时应排程成功。
    multi = {"input": {
        "layers": [
            {"id": 1, "duration": 2, "predecessors": [], "flash": True, "flash_duration": 2,
             "window_successor": 3, "wait_min": 0, "wait_max": 6},
            {"id": 2, "duration": 2, "predecessors": [], "flash": True, "flash_duration": 2,
             "window_successor": 3, "wait_min": 0, "wait_max": 6},
            {"id": 3, "duration": 2, "predecessors": [1, 2], "flash": False},
        ],
        "press_windows": [{"start": 0, "end": 40}],
        "oven_windows": [{"start": 0, "end": 40}],
    }, "fix_positions": []}
    mc = post("/api/schedule", multi)
    check(mc["feasible"] is True, "两个合法窗口有共同时间时排程成功")

    # 5) 采纳快照：合法可冻结，且快照 request 重开结果一致。
    snap = post("/api/adopt", greedy)
    check(snap.get("version") == 1 and snap["solution"]["print_sequence"] == [2, 1, 3],
          "采纳合法工艺单并冻结")
    again = post("/api/schedule", snap["request"])
    check(again["print_sequence"] == snap["solution"]["print_sequence"]
          and again["makespan"] == snap["solution"]["makespan"],
          "快照可原样重开且解一致")

    # 5b) 非法工艺输入不能被采纳（409 + 冲突）。
    bad_adopt = {"input": {
        "layers": [
            {"id": 1, "duration": 2, "window_successor": 2},
            {"id": 2, "duration": 2, "predecessors": [1]},
        ],
        "press_windows": [{"start": 0, "end": 20}],
        "oven_windows": [{"start": 0, "end": 20}],
    }, "fix_positions": []}
    req = urllib.request.Request(
        BASE + "/api/adopt",
        data=json.dumps(bad_adopt).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(req)
        print("❌ 非法工艺输入不应被采纳")
        sys.exit(1)
    except urllib.error.HTTPError as e:
        body = json.load(e)
        check(e.code == 409 and body["feasible"] is False
              and body["conflicts"][0]["type"] == "WINDOW_ON_NON_FLASH",
              "非法工艺输入采纳被拒（409 + 冲突类型）")

    # 6) 空图层作业：返回明确的 EMPTY_LAYERS 冲突，而不是服务端错误。
    empty = {"input": {
        "layers": [],
        "press_windows": [{"start": 0, "end": 10}],
        "oven_windows": [{"start": 0, "end": 10}],
    }, "fix_positions": []}
    ec = post("/api/schedule", empty)
    check(ec["feasible"] is False
          and ec["conflicts"][0]["type"] == "EMPTY_LAYERS",
          "空图层作业返回 EMPTY_LAYERS 而非 500")

    print("\n✅ compose verify：五类验收 + 多窗口 + 采纳拦截 + 空作业全部通过")


if __name__ == "__main__":
    main()
