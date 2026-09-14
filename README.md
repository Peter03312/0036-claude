# 丝网套印编排台（Screen-Printing Overprint Orchestration Console）

从空仓库起步、**React + TypeScript 前端联调 FastAPI 后端**的套印编排台。
排程员上传**图层 JSON**与**印台 / 烘台可用时段 CSV**，后端对刮印次序、闪干次序
及各操作起止做**完整搜索**，在双时间轴上展示排程、依赖边与复涂窗口余量；
可固定图层在完整刮印序列中的位置重算；采纳后冻结输入与工艺单，可导出并
原样重开。

---

## 1. 业务约束（建模口径）

- 每个图层有：**唯一整数编号** `id`、`duration` 刮印时长、`predecessors` 前驱、
  `wet_group` 湿碰湿组、`flash` 是否闪干、`flash_duration` 闪干时长、
  `window_successor` 窗口后继，以及 `wait_min / wait_max` 等待上下限。
- **仅闪干层可设窗口后继**（非闪干层设置会在静态校验报 `WINDOW_ON_NON_FLASH`）。
- 前驱的刮印必须**先结束**：`ps_s ≥ ps_p + duration_p`。
- 闪干开始**不得早于**该层刮印结束：`fs_i ≥ ps_i + duration_i`；闪干在唯一烘台上
  可延后安排（与印台刮印并行）。
- **复涂窗口**：窗口后继刮印必须始于闪干结束后的闭区间
  `fe_f + wait_min ≤ ps_s ≤ fe_f + wait_max`。
- **设备区间左闭右开** `[start, end)`；每个操作 `[t, t+duration)` 必须完整落在
  某一个可用时段内。
- **单印台、单烘台各自互斥**（任意两块刮印 / 任意两段闪干不得重叠）。
- **湿碰湿同组层**依前驱在印台**首尾相接**：组内相邻两块
  `ps_b = ps_a + duration_a`，中间既无空闲，也不插入组外刮印。组必须构成一条
  覆盖全组的链（静态校验 `WET_GROUP_NOT_CHAIN`）。

### 为什么"逐层排最早"会把可行作业排死

前驱只给**偏序**，逐层（如按编号）排最早会过早提交资源次序与闪干时刻；
湿碰湿层必须连续、闪干后的后继又必须落进复涂窗口。设备时段的一个**间隙**就可能
让贪心选定的次序跨过断点、把后继顶出窗口。本系统对**印台刮印次序**与
**烘台闪干次序**做完整搜索，并在每个固定次序下用差分约束求时间，从而找到
贪心错失的换序解（见验收场景一）。

---

## 2. 优化目标（字典序）

对每一对（印台次序 π，烘台闪干次序 σ），分两阶段求时间：

1. **最早阶段**：刮印与闪干起点构成差分约束系统 `x_v − x_u ≥ c`（前驱先结束、
   闪干不早于刮印结束、湿碰湿首尾相接、复涂窗口上下限、两机互斥），用队列式
   Bellman–Ford（SPFA）求分量意义上最早的可行解，**正环即该次序无解**；设备时段
   是析取约束，用"最早落位锚定"单调迭代把操作锚进具体可用时段。此阶段确定最小
   makespan。
2. **最晚闪干阶段**：刮印固定为最早时刻，在 `闪干结束 ≤ 最小 makespan` 上限下，
   沿烘台次序反向传播上界并"最晚落位"，把各闪干排到分量最晚——因为每段窗口等待
   `ps_s − fe_f` 随 `fs_f` 单调下降，这同时最小化窗口等待总和。

然后在所有 (π, σ) 间依次比较，取字典序最优：

1. **最晚结束时刻** makespan 最小；
2. **窗口等待总和** `Σ(ps_s − fe_f)` 最小；
3. **刮印编号序列**字典序最小；
4. 按该序列排列的**刮印起点序列**字典序最小；
5. 按该序列排列的**闪干起点序列**字典序最小。

**无解**时返回冲突**约束类型**与涉及**图层**，包括（但不限于）：

| 类型 | 含义 |
| --- | --- |
| `UNKNOWN_PREDECESSOR` / `UNKNOWN_WINDOW_SUCCESSOR` | 引用了不存在的图层 |
| `DEPENDENCY_CYCLE` | 前驱偏序有环 |
| `WINDOW_ON_NON_FLASH` | 非闪干层设置窗口后继 |
| `BAD_WINDOW_BOUNDS` | 等待下限大于上限 |
| `WET_GROUP_NOT_CHAIN` / `WET_GROUP_SINGLE` | 湿碰湿组不构成链 |
| `MULTIPLE_WINDOW_PREDECESSORS` | 一个后继被多个窗口约束 |
| `PRESS_WINDOW_TOO_SHORT` / `OVEN_WINDOW_TOO_SHORT` | 单个时段容不下操作 |
| `WET_GROUP_SPLIT` | 时段间隙切断湿碰湿连续组 |
| `WINDOW_INFEASIBLE` | 复涂窗口本身杀死所有排法（放开设备时段仍无解） |
| `DEVICE_WINDOW_INFEASIBLE` | 设备时段与先后约束配合不上 |
| `NO_FEASIBLE_SCHEDULE` | 放开设备/湿碰湿/窗口后核心互斥+偏序仍矛盾 |
| `FIX_*` | 固定位置越界 / 冲突 / 违反偏序 |

诊断方式：在搜索中逐类**放开约束**（无限设备时段 → 放开湿碰湿无空闲等式 →
放开窗口上下限），第一个由"无解"变"可行"的约束类即冲突根因。

---

## 3. 目录结构

```
.
├── backend/
│   ├── app/
│   │   ├── main.py          # FastAPI 路由 / 采纳快照
│   │   ├── models.py        # Pydantic 模型
│   │   ├── parser.py        # JSON/CSV 解析 + 静态校验（错误可定位）
│   │   ├── scheduler.py     # 完整搜索引擎（枚举次序 + Bellman-Ford）
│   │   ├── diagnostics.py   # 无解冲突分类
│   │   └── samples.py       # 内置验收样例
│   ├── samples/             # 可上传的 layers.json / press.csv / oven.csv
│   ├── tests/               # pytest 用例
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── App.tsx          # 编排台主界面
│   │   ├── components/
│   │   │   ├── Timeline.tsx # 双时间轴 + 依赖边 + 窗口余量
│   │   │   └── FixPanel.tsx # 固定图层位置
│   │   └── lib/             # 类型、API、本地解析、时间轴几何（含单测）
│   ├── Dockerfile + nginx.conf
├── docker-compose.yml
├── verify.sh                # 一次性验收
└── README.md
```

---

## 4. 用 Docker Compose 启动两端

```bash
docker compose up --build
```

- 前端（Web）：<http://localhost:8080>
- 后端（API）：<http://localhost:8000>（健康检查 `/api/health`）

**覆盖宿主端口**：

```bash
WEB_PORT=9090 API_PORT=9000 docker compose up --build
```

前端容器内 nginx 把 `/api/*` 反代到 `api:8000`，浏览器同源访问；后端 CORS 亦
默认放开，便于直接调用。

---

## 5. 本地开发（不用 Docker）

```bash
# 后端
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# 前端（dev server 把 /api 代理到 VITE_API_TARGET，默认 http://localhost:8000）
cd frontend
npm install
npm run dev
```

---

## 6. 输入文件格式

### layers.json（顶层数组，或 `{"layers": [...]}`）

```json
[
  {
    "id": 1,
    "duration": 3,
    "predecessors": [],
    "wet_group": null,
    "flash": true,
    "flash_duration": 3,
    "window_successor": 3,
    "wait_min": 0,
    "wait_max": 1
  }
]
```

### press.csv / oven.csv（表头必须含 `start,end`，左闭右开）

```csv
start,end
0,10
10,19
```

解析错误会精确定位到**文件与行/字段**（如 `press.csv 第 2 行: start/end 必须是数值`）。

---

## 7. HTTP API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 健康检查 |
| GET | `/api/sample` | 内置"贪心失窗"示例输入 |
| POST | `/api/parse` | multipart 上传三个文件，返回规范化输入与静态冲突 |
| POST | `/api/schedule` | JSON body `{input, fix_positions}`，返回解或冲突 |
| POST | `/api/schedule/upload` | multipart 上传并直接编排 |
| POST | `/api/adopt` | 重算并冻结为工艺单快照（含 `version/adopted_at/request/solution`） |

`fix_positions` 形如 `[{"layer_id": 3, "position": 2}]`，位置从 **1** 起。
快照 JSON 可下载保存，之后在界面"重开工艺单快照"原样载入。

---

## 8. 验收（一键 verify）

`verify.sh` 一次性完成：后端 pytest、前端 vitest 与 **TypeScript/生产构建**、
真实启动 uvicorn + 静态服务器后的**端到端 HTTP 冒烟**，覆盖题目要求的五类场景：

```bash
./verify.sh                                 # 默认 API 18000 / Web 18080
API_PORT=19000 WEB_PORT=19080 ./verify.sh
```

验收场景：

1. **贪心错失窗口但换序可行**：编号序（用固定位置强制）无解，搜索得 `[2,1,3]`，
   图层 1 落入第二时段、后继等待 0 ∈ [0,1]、余量 1；
2. **两设备合法并行**：闪干 1 `[4,10)` 与刮印 2 `[4,9)` 在印台/烘台上重叠；
3. **时段间隙切断湿碰湿组**：返回 `WET_GROUP_SPLIT` 与图层 `[1,2,3]`；
4. **真正无解**：窗口与前驱构成正环，返回 `WINDOW_INFEASIBLE`；
5. **采纳快照**：`/api/adopt` 冻结，快照 request 重算结果一致，可导出重开。

单独跑测试：

```bash
cd backend && python -m pytest -q
cd frontend && npm run test && npm run build
```

---

## 9. 前端使用

1. 选择三个文件后点 **解析载入**（或点"载入内置示例"）；本地即时解析，后端做
   权威静态校验。
2. （可选）在"固定图层位置"表为某层指定序列位置，点 **完整搜索 / 重算**。
3. 有解：查看双时间轴——**蓝块刮印 / 橙块闪干 / 紫框湿碰湿层**，虚线为前驱
   依赖（湿碰湿边为紫实线），`▲` 标注每段复涂等待、窗口区间与**余量**；
   下方为逐图层时序明细。
4. 无解：展示冲突类型、说明与涉及图层徽标。
5. 点 **采纳并冻结** 后输入锁定，可 **导出工艺单 JSON**；日后用
   "重开工艺单快照"原样恢复。

时间单位在输入中保持一致即可（示例按分钟），求解与显示不做隐式换算。
