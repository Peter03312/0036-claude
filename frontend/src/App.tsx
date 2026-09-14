import { useEffect, useMemo, useState } from "react";
import type {
  AdoptSnapshot,
  Conflict,
  FixPosition,
  ScheduleInput,
  ScheduleResult,
  ScheduleSolution,
} from "./lib/types";
import { isSolution } from "./lib/types";
import { adopt, downloadJson, fetchSample, schedule, uploadFiles } from "./lib/api";
import { parseLayersJson, parseWindowsCsv, LocalParseError } from "./lib/parse";
import { Timeline } from "./components/Timeline";
import { FixPanel } from "./components/FixPanel";
import { fmt } from "./lib/timeline";

type LoadedInput = ScheduleInput | null;

export default function App() {
  const [input, setInput] = useState<LoadedInput>(null);
  const [files, setFiles] = useState<{ layers?: File; press?: File; oven?: File }>({});
  const [fixes, setFixes] = useState<FixPosition[]>([]);
  const [result, setResult] = useState<ScheduleResult | null>(null);
  const [localError, setLocalError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [snapshot, setSnapshot] = useState<AdoptSnapshot | null>(null);

  // 载入内置示例。
  async function loadSample() {
    setLocalError(null);
    const inp = await fetchSample();
    setInput(inp);
    setFiles({});
    setFixes([]);
    setSnapshot(null);
    // 关键：切换输入必须清空上一次排程结果，否则旧时序与新图层不匹配会崩溃。
    setResult(null);
  }

  useEffect(() => {
    loadSample().catch((e) => setLocalError(String(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function pickFile(kind: "layers" | "press" | "oven", file: File | undefined) {
    setFiles((f) => ({ ...f, [kind]: file }));
  }

  async function parseUploads() {
    setLocalError(null);
    if (!files.layers || !files.press || !files.oven) {
      setLocalError("请先选择图层 JSON、印台 CSV 与烘台 CSV 三个文件");
      return;
    }
    try {
      // 本地先解析给出即时反馈。
      const [layerText, pressText, ovenText] = await Promise.all(
        [files.layers, files.press, files.oven].map((f) => f!.text()),
      );
      const layers = parseLayersJson(layerText);
      const press_windows = parseWindowsCsv(pressText, "press.csv");
      const oven_windows = parseWindowsCsv(ovenText, "oven.csv");
      // 再经后端做权威静态校验（引用/环/湿碰湿组结构）。
      const parsed = await uploadFiles(files.layers, files.press, files.oven);
      void parsed;
      setInput({ layers, press_windows, oven_windows });
      setFixes([]);
      setResult(null);
      setSnapshot(null);
    } catch (e) {
      if (e instanceof LocalParseError) {
        setLocalError(`${e.location}：${e.message}`);
      } else {
        setLocalError(
          e instanceof Error
            ? `${(e as { location?: string }).location ?? "上传"}：${e.message}`
            : String(e),
        );
      }
    }
  }

  async function runSchedule() {
    if (!input) return;
    setBusy(true);
    setLocalError(null);
    try {
      setResult(await schedule(input, fixes));
    } catch (e) {
      setLocalError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function adoptSolution() {
    if (!input || !result || !isSolution(result)) return;
    setBusy(true);
    setLocalError(null);
    try {
      const resp = await adopt(input, fixes);
      // 后端在非法/无解时返回冲突结构（HTTP 409），不冻结。
      if ("feasible" in resp && resp.feasible === false) {
        setResult(resp);
        return;
      }
      const snap = resp as AdoptSnapshot;
      if (snap.version !== 1 || !snap.solution) {
        setLocalError("采纳失败：返回的快照结构不完整");
        return;
      }
      setSnapshot(snap);
      // 冻结输入：以快照中的请求为准。
      setInput(structuredClone(snap.request.input));
      setFixes(structuredClone(snap.request.fix_positions));
      setResult(snap.solution);
    } catch (e) {
      setLocalError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  function reopenSnapshot(file: File) {
    file
      .text()
      .then((text) => {
        const snap = JSON.parse(text) as AdoptSnapshot;
        if (snap.version !== 1 || !snap.request || !snap.solution) {
          throw new Error("不是有效的工艺单快照");
        }
        setSnapshot(snap);
        setInput(snap.request.input);
        setFixes(snap.request.fix_positions);
        setResult(snap.solution);
        setLocalError(null);
      })
      .catch((e) => setLocalError(`快照重开失败：${String(e.message ?? e)}`));
  }

  const solution: ScheduleSolution | null =
    result && isSolution(result) ? result : null;
  const conflicts: Conflict[] =
    result && !isSolution(result) ? result.conflicts : [];

  const timelineWidth = useMemo(() => 1080, []);

  return (
    <div className="app">
      <h1>丝网套印编排台</h1>
      <p className="subtitle">
        单印台 / 单烘台 · 前驱偏序 · 湿碰湿连续刮印 · 闪干复涂窗口 · 完整搜索最优排程
      </p>

      {localError && <div className="error-box">{localError}</div>}

      <section className="panel">
        <h2>① 上传图层与设备时段</h2>
        <div className="row">
          <label className="file-label">
            图层 JSON
            <input
              type="file"
              accept=".json,application/json"
              onChange={(e) => pickFile("layers", e.target.files?.[0])}
            />
          </label>
          <label className="file-label">
            印台时段 CSV
            <input
              type="file"
              accept=".csv"
              onChange={(e) => pickFile("press", e.target.files?.[0])}
            />
          </label>
          <label className="file-label">
            烘台时段 CSV
            <input
              type="file"
              accept=".csv"
              onChange={(e) => pickFile("oven", e.target.files?.[0])}
            />
          </label>
          <button onClick={parseUploads} disabled={snapshot != null}>
            解析载入
          </button>
          <button className="secondary" onClick={loadSample} disabled={snapshot != null}>
            载入内置示例
          </button>
          <label className="file-label">
            重开工艺单快照
            <input
              type="file"
              accept=".json"
              onChange={(e) => e.target.files?.[0] && reopenSnapshot(e.target.files[0])}
            />
          </label>
        </div>
        {input && (
          <p className="tag" style={{ marginTop: 10 }}>
            已载入 {input.layers.length} 个图层；印台 {input.press_windows.length} 段、
            烘台 {input.oven_windows.length} 段可用时段（左闭右开）。
          </p>
        )}
      </section>

      {input && (
        <section className="panel">
          <h2>② 固定图层位置（可选）并重算</h2>
          <FixPanel
            layers={input.layers}
            fixes={fixes}
            onChange={setFixes}
            disabled={snapshot != null}
          />
          <div className="row" style={{ marginTop: 12 }}>
            <button onClick={runSchedule} disabled={busy || snapshot != null}>
              {busy ? "搜索中…" : "完整搜索 / 重算"}
            </button>
            {solution && (
              <button
                className="secondary"
                onClick={adoptSolution}
                disabled={busy || snapshot != null}
              >
                采纳并冻结
              </button>
            )}
          </div>
        </section>
      )}

      {snapshot && (
        <div className="locked-banner">
          ✅ 已采纳冻结（{snapshot.adopted_at}）。输入与工艺单已锁定，可导出后原样重开。
          <button
            className="secondary"
            style={{ marginLeft: 12 }}
            onClick={() =>
              downloadJson(
                `process-sheet-${snapshot.solution.print_sequence.join("-")}.json`,
                snapshot,
              )
            }
          >
            导出工艺单 JSON
          </button>
        </div>
      )}

      {conflicts.length > 0 && (
        <div className="error-box">
          <h3>无解：检测到 {conflicts.length} 类冲突约束</h3>
          {conflicts.map((c, i) => (
            <div className="conflict" key={i}>
              <code>{c.type}</code> — {c.message}
              {c.layers.length > 0 && (
                <div className="layer-chips">
                  涉及图层：
                  {c.layers.map((id, j) => (
                    <span key={j}>#{id}</span>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {solution && input && (
        <>
          <section className="panel">
            <h2>③ 双时间轴</h2>
            <div className="solution-banner">
              <span className="stat">
                <b>{fmt(solution.makespan)}</b>最晚结束时刻
              </span>
              <span className="stat">
                <b>{fmt(solution.window_wait_sum)}</b>窗口等待总和
              </span>
              <span className="stat">
                刮印序列：
                {solution.print_sequence.map((id, i) => (
                  <span className="seq-pill" key={i}>
                    <b>{i + 1}</b> #{id}
                  </span>
                ))}
              </span>
            </div>
            <Timeline input={input} solution={solution} width={timelineWidth} />
          </section>

          <section className="panel">
            <h2>④ 工艺时序明细</h2>
            <table>
              <thead>
                <tr>
                  <th>图层</th>
                  <th>刮印 [起, 止)</th>
                  <th>闪干 [起, 止)</th>
                  <th>前驱</th>
                  <th>湿碰湿组</th>
                  <th>窗口后继</th>
                  <th>实际等待 / 窗口</th>
                  <th>余量</th>
                </tr>
              </thead>
              <tbody>
                {input.layers.map((l) => {
                  const t = solution.timings[String(l.id)];
                  if (!t) return null;
                  return (
                    <tr key={l.id}>
                      <td>#{l.id}</td>
                      <td>
                        {fmt(t.press_start)} – {fmt(t.press_end)}
                      </td>
                      <td>
                        {t.flash_start != null && t.flash_end != null
                          ? `${fmt(t.flash_start)} – ${fmt(t.flash_end)}`
                          : "—"}
                      </td>
                      <td>{l.predecessors.map((p) => `#${p}`).join(" ") || "—"}</td>
                      <td>{l.wet_group ?? "—"}</td>
                      <td>{l.window_successor ? `#${l.window_successor}` : "—"}</td>
                      <td>
                        {t.window_wait != null
                          ? `${fmt(t.window_wait)} / [${fmt(l.wait_min)}, ${fmt(l.wait_max)}]`
                          : "—"}
                      </td>
                      <td>{t.window_slack != null ? fmt(t.window_slack) : "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </section>
        </>
      )}
    </div>
  );
}
