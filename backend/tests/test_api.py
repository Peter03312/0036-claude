"""端到端验收测试（经 FastAPI）。"""
from __future__ import annotations

from app import samples


def _post_sample(client, name, fix_positions=None):
    payload = getattr(samples, name)()
    return client.post(
        "/api/schedule",
        json={"input": payload, "fix_positions": fix_positions or []},
    )


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_greedy_misses_window_but_reorder_feasible(client):
    """逐层最早（编号序）排死，换序 [2,1,3] 可行且窗口闭合。"""
    r = _post_sample(client, "greedy_miss_sample")
    assert r.status_code == 200
    data = r.json()
    assert data["feasible"] is True
    assert data["print_sequence"] == [2, 1, 3]

    t = {x["layer_id"]: x for x in data["timings"].values()}
    # 图层 1 落在印台第二时段 [10,19)，闪干紧接其后。
    assert t[1]["press_start"] == 10
    assert t[1]["flash_start"] == 13 and t[1]["flash_end"] == 16
    # 后继 3 始于 16，闪干 16 结束，等待 0 ∈ [0,1]，余量 1。
    assert t[3]["press_start"] == 16
    assert t[1]["window_wait"] == 0
    assert t[1]["window_slack"] == 1
    # 编号序（贪心）在该设备时段下不可行，由固定位置强制复现：
    bad = _post_sample(client, "greedy_miss_sample", [
        {"layer_id": 1, "position": 1},
        {"layer_id": 2, "position": 2},
        {"layer_id": 3, "position": 3},
    ]).json()
    assert bad["feasible"] is False
    assert bad["conflicts"]  # 有冲突类型与图层
    assert any(c["layers"] for c in bad["conflicts"])


def test_two_devvels_run_in_parallel(client):
    """烘台闪干与印台刮印合法并行（两设备同时在工作）。"""
    r = _post_sample(client, "parallel_sample")
    data = r.json()
    assert data["feasible"] is True
    t = {x["layer_id"]: x for x in data["timings"].values()}
    # 闪干 1 不早于刮印 1 结束 4，且与印台上的刮印 2/3 在时间上重叠
    # （不同设备同时工作）。
    assert t[1]["flash_start"] >= 4
    assert t[1]["flash_start"] < t[3]["press_end"]
    # 刮印 2 [4,9) 期间，烘台正在闪干 1。
    assert t[1]["flash_start"] < t[2]["press_end"]
    assert t[2]["press_start"] < t[1]["flash_end"]


def test_window_gap_cuts_wet_group(client):
    r = _post_sample(client, "wet_split_sample")
    data = r.json()
    assert data["feasible"] is False
    c = data["conflicts"][0]
    assert c["type"] == "WET_GROUP_SPLIT"
    assert c["layers"] == [1, 2, 3]


def test_genuinely_infeasible_window(client):
    r = _post_sample(client, "infeasible_window_sample")
    data = r.json()
    assert data["feasible"] is False
    types = {c["type"] for c in data["conflicts"]}
    assert types & {"WINDOW_INFEASIBLE", "DEVICE_WINDOW_INFEASIBLE"}
    # 必须指出涉及图层。
    assert any(c["layers"] for c in data["conflicts"])


def test_device_window_infeasible(client):
    payload = {
        "layers": [
            {"id": 1, "duration": 4, "flash": True, "flash_duration": 4,
             "window_successor": 2, "wait_min": 0, "wait_max": 0},
            {"id": 2, "duration": 2, "predecessors": [1]},
        ],
        "press_windows": [{"start": 0, "end": 6}, {"start": 20, "end": 30}],
        "oven_windows": [{"start": 0, "end": 12}],
    }
    data = client.post("/api/schedule", json={"input": payload}).json()
    assert data["feasible"] is False
    assert any(
        c["type"] in ("DEVICE_WINDOW_INFEASIBLE", "PRESS_WINDOW_TOO_SHORT")
        for c in data["conflicts"]
    )


def test_fix_position_recalculates(client):
    # 固定图层 3 在第 3 位，仍是换序解。
    data = _post_sample(client, "greedy_miss_sample", [
        {"layer_id": 3, "position": 3}
    ]).json()
    assert data["feasible"] is True
    assert data["print_sequence"][2] == 3


def test_fix_impossible_position_conflict(client):
    data = _post_sample(client, "greedy_miss_sample", [
        {"layer_id": 3, "position": 1}
    ]).json()
    assert data["feasible"] is False
    assert data["conflicts"]


def test_adopt_snapshot_roundtrip(client):
    payload = samples.greedy_miss_sample()
    r = client.post("/api/adopt", json={"input": payload, "fix_positions": []})
    assert r.status_code == 200
    snap = r.json()
    assert snap["version"] == 1
    assert snap["solution"]["print_sequence"] == [2, 1, 3]
    assert "adopted_at" in snap
    # 快照可原样重开：把其中的 request 再提交，解一致。
    r2 = client.post("/api/schedule", json=snap["request"])
    again = r2.json()
    assert again["print_sequence"] == snap["solution"]["print_sequence"]
    assert again["makespan"] == snap["solution"]["makespan"]


def test_upload_endpoint(client, tmp_path):
    import json
    payload = samples.greedy_miss_sample()
    layers_p = tmp_path / "layers.json"
    layers_p.write_text(json.dumps(payload["layers"]), encoding="utf-8")
    press_p = tmp_path / "press.csv"
    press_p.write_text("start,end\n0,10\n10,19\n", encoding="utf-8")
    oven_p = tmp_path / "oven.csv"
    oven_p.write_text("start,end\n0,6\n6,46\n", encoding="utf-8")
    with open(layers_p, "rb") as a, open(press_p, "rb") as b, open(oven_p, "rb") as c:
        r = client.post(
            "/api/schedule/upload",
            files={"layers": a, "press": b, "oven": c},
            data={"fix_positions": "[]"},
        )
    assert r.status_code == 200
    assert r.json()["print_sequence"] == [2, 1, 3]


def test_parse_error_is_located(client, tmp_path):
    bad_json = b'[{"id": 1, duration: 2}]'  # 非法 JSON
    r = client.post(
        "/api/parse",
        files={
            "layers": ("layers.json", bad_json, "application/json"),
            "press": ("press.csv", b"start,end\n0,10\n", "text/csv"),
            "oven": ("oven.csv", b"start,end\n0,10\n", "text/csv"),
        },
    )
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert "layers.json" in detail["location"]
    assert "message" in detail


def test_csv_error_is_located(client):
    import json
    layers = json.dumps([{"id": 1, "duration": 2}])
    r = client.post(
        "/api/parse",
        files={
            "layers": ("layers.json", layers, "application/json"),
            "press": ("press.csv", b"start,end\n0,bad\n", "text/csv"),
            "oven": ("oven.csv", b"start,end\n0,10\n", "text/csv"),
        },
    )
    assert r.status_code == 422
    assert "第 2 行" in r.json()["detail"]["location"]


def test_static_validation_window_on_non_flash(client):
    payload = {
        "layers": [
            {"id": 1, "duration": 2, "window_successor": 2},
            {"id": 2, "duration": 2, "predecessors": [1]},
        ],
        "press_windows": [{"start": 0, "end": 20}],
        "oven_windows": [{"start": 0, "end": 20}],
    }
    data = client.post("/api/schedule", json={"input": payload}).json()
    assert data["feasible"] is False
    assert data["conflicts"][0]["type"] == "WINDOW_ON_NON_FLASH"


def test_static_validation_cycle(client):
    payload = {
        "layers": [
            {"id": 1, "duration": 2, "predecessors": [2]},
            {"id": 2, "duration": 2, "predecessors": [1]},
        ],
        "press_windows": [{"start": 0, "end": 20}],
        "oven_windows": [{"start": 0, "end": 20}],
    }
    data = client.post("/api/schedule", json={"input": payload}).json()
    assert data["feasible"] is False
    assert data["conflicts"][0]["type"] == "DEPENDENCY_CYCLE"
