#!/usr/bin/env bash
# 一次性验收：后端测试 + 生产构建（前端 tsc/vite build）+ 真实服务端到端冒烟。
# 用法：./verify.sh   （在仓库根目录执行）
# 不依赖 Docker：直接用本机 python/node 启动 uvicorn 与静态产物做联调验证。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

API_PORT="${API_PORT:-18000}"
WEB_PORT="${WEB_PORT:-18080}"
API_BASE="http://127.0.0.1:${API_PORT}"

echo "==> [1/5] 后端静态检查与单元/接口测试"
cd "$ROOT/backend"
PY="python3"
if python3 -m venv .verify-venv 2>/dev/null; then
  # shellcheck disable=SC1091
  source .verify-venv/bin/activate
  pip install --quiet --upgrade pip
  pip install --quiet -r requirements.txt
  PY="python"
else
  echo "    （无法创建 venv，回退到系统 Python：$PY）"
fi
$PY -m pytest -q
[ "$PY" = "python" ] && deactivate || true

echo "==> [2/5] 前端类型检查、单元测试与生产构建"
cd "$ROOT/frontend"
if [ ! -d "node_modules" ]; then
  npm install --no-audit --no-fund
fi
npm run test
npm run build

echo "==> [3/5] 启动后端服务 (${API_BASE})"
cd "$ROOT/backend"
if [ "$PY" = "python" ]; then
  # shellcheck disable=SC1091
  source .verify-venv/bin/activate
fi
$PY -m uvicorn app.main:app --host 127.0.0.1 --port "$API_PORT" \
  > "$ROOT/.verify-api.log" 2>&1 &
API_PID=$!
trap 'kill $API_PID $WEB_PID 2>/dev/null || true' EXIT

for _ in $(seq 1 50); do
  if curl -sf "$API_BASE/api/health" >/dev/null 2>&1; then break; fi
  sleep 0.3
done
curl -sf "$API_BASE/api/health" | grep -q '"ok"'
echo "    health OK"

echo "==> [4/5] 提供前端静态产物 (http://127.0.0.1:${WEB_PORT})"
cd "$ROOT/frontend"
npx vite preview --host 127.0.0.1 --port "$WEB_PORT" \
  > "$ROOT/.verify-web.log" 2>&1 &
WEB_PID=$!
for _ in $(seq 1 50); do
  if curl -sf "http://127.0.0.1:${WEB_PORT}/" >/dev/null 2>&1; then break; fi
  sleep 0.3
done
INDEX="$(curl -sf http://127.0.0.1:${WEB_PORT}/)"
echo "$INDEX" | grep -q "丝网套印编排台"
echo "    static index OK"

echo "==> [5/5] 端到端接口冒烟（四类验收场景 + 快照）"
python3 - "$API_BASE" "$ROOT/backend/samples/layers.json" <<'PY'
import json, sys, urllib.request, os

base = sys.argv[1]
samples_path = sys.argv[2]

def post(path, payload):
    req = urllib.request.Request(
        base + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as r:
        return json.load(r)

with open(samples_path, encoding="utf-8") as f:
    layers = json.load(f)
greedy = {
    "input": {
        "layers": layers,
        "press_windows": [{"start": 0, "end": 10}, {"start": 10, "end": 19}],
        "oven_windows": [{"start": 0, "end": 6}, {"start": 6, "end": 46}],
    },
    "fix_positions": [],
}
sol = post("/api/schedule", greedy)
assert sol["feasible"] and sol["print_sequence"] == [2, 1, 3], sol
print("    贪心失窗/换序可行 OK：", sol["print_sequence"], "makespan", sol["makespan"])

# 强制贪心编号序 -> 必须有冲突
forced = dict(greedy)
forced["fix_positions"] = [
    {"layer_id": 1, "position": 1},
    {"layer_id": 2, "position": 2},
    {"layer_id": 3, "position": 3},
]
bad = post("/api/schedule", forced)
assert bad["feasible"] is False and bad["conflicts"], bad
print("    贪心序排死冲突 OK：", bad["conflicts"][0]["type"])

# 两设备并行：闪干 1 [4,10) 与刮印 2 [4,9) 时间重叠
parallel = {"input": {
    "layers": [
        {"id": 1, "duration": 4, "flash": True, "flash_duration": 6},
        {"id": 2, "duration": 5, "predecessors": [1]},
        {"id": 3, "duration": 2, "predecessors": [2]},
    ],
    "press_windows": [{"start": 0, "end": 20}],
    "oven_windows": [{"start": 0, "end": 20}],
}, "fix_positions": []}
ps = post("/api/schedule", parallel)
t = {k: v for k, v in ps["timings"].items()}
# 闪干不早于刮印1结束4，且与印台上的刮印2[4,9)时间重叠（两设备同时工作）。
assert float(t["1"]["flash_start"]) >= 4.0, ps
assert float(t["1"]["flash_start"]) < float(t["2"]["press_end"]), ps
assert float(t["2"]["press_start"]) < float(t["1"]["flash_end"]), ps
print("    两设备并行 OK：闪干", t["1"]["flash_start"], t["1"]["flash_end"],
      "刮印2", t["2"]["press_start"], t["2"]["press_end"])

# 间隙切断湿碰湿组
wet = {"input": {
    "layers": [
        {"id": 1, "duration": 4, "wet_group": "A"},
        {"id": 2, "duration": 4, "predecessors": [1], "wet_group": "A"},
        {"id": 3, "duration": 4, "predecessors": [2], "wet_group": "A"},
    ],
    "press_windows": [{"start": 0, "end": 6}, {"start": 10, "end": 16}],
    "oven_windows": [{"start": 0, "end": 30}],
}, "fix_positions": []}
wc = post("/api/schedule", wet)
assert wc["feasible"] is False
assert wc["conflicts"][0]["type"] == "WET_GROUP_SPLIT", wc
print("    间隙切断湿碰湿组 OK")

# 真正无解：零等待窗口与两台时段错配（闪干在烘台 [0,10) 内无论怎么延后，
# 都无法把后继刮印对齐到印台 [0,4)+[20,30) 的开放时刻）。
infeasible = {"input": {
    "layers": [
        {"id": 1, "duration": 3, "flash": True, "flash_duration": 4,
         "window_successor": 2, "wait_min": 0, "wait_max": 0},
        {"id": 2, "duration": 2, "predecessors": [1]},
    ],
    "press_windows": [{"start": 0, "end": 4}, {"start": 20, "end": 30}],
    "oven_windows": [{"start": 0, "end": 10}],
}, "fix_positions": []}
ic = post("/api/schedule", infeasible)
assert ic["feasible"] is False
types = {c["type"] for c in ic["conflicts"]}
assert types & {"WINDOW_INFEASIBLE", "DEVICE_WINDOW_INFEASIBLE"}, ic
assert any(c["layers"] for c in ic["conflicts"]), ic
print("    真正无解冲突类型 OK：", [c["type"] for c in ic["conflicts"]])

# 采纳快照 -> 用快照 request 重算一致
snap = post("/api/adopt", greedy)
assert snap["version"] == 1 and snap["solution"]["print_sequence"] == [2, 1, 3]
again = post("/api/schedule", snap["request"])
assert again["print_sequence"] == snap["solution"]["print_sequence"]
print("    采纳快照/原样重开 OK，adopted_at =", snap["adopted_at"])
PY

echo ""
echo "✅ verify 全部通过：后端测试、前端测试与生产构建、真实服务端到端冒烟。"
