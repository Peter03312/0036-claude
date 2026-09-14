import { useMemo } from "react";
import type {
  Interval,
  Layer,
  ScheduleSolution,
} from "../lib/types";
import { buildScale, fmt, widthOf, xOf } from "../lib/timeline";

interface Props {
  input: { layers: Layer[]; press_windows: Interval[]; oven_windows: Interval[] };
  solution: ScheduleSolution;
  width?: number;
}

const LABEL_W = 64;

// 依赖边：从一个刮印块的右端连到后继刮印块的左端（在印台轨上）。
function dependencyEdges(
  layers: Layer[],
  timings: ScheduleSolution["timings"],
  scale: ReturnType<typeof buildScale>,
  yTop: number,
) {
  const byId = new Map(layers.map((l) => [l.id, l]));
  const edges: { d: string; key: string; wet: boolean }[] = [];
  layers.forEach((l) => {
    l.predecessors.forEach((p) => {
      const pred = byId.get(p);
      const from = timings[String(p)];
      const to = timings[String(l.id)];
      if (!pred || !from || !to) return;
      const x1 = xOf(scale, from.press_end);
      const x2 = xOf(scale, to.press_start);
      const wet = pred.wet_group !== null && pred.wet_group === l.wet_group;
      // 从源块右缘下弯，再进入目标块左缘。
      const midY = yTop + 30;
      const d = `M ${x1} ${yTop + 11} C ${x1} ${midY}, ${x2} ${midY}, ${x2} ${yTop + 11}`;
      edges.push({ d, key: `${p}->${l.id}`, wet });
    });
  });
  return edges;
}

export function Timeline({ input, solution, width = 1080 }: Props) {
  const innerW = width - LABEL_W;
  const scale = useMemo(() => {
    const times: number[] = [];
    [...input.press_windows, ...input.oven_windows].forEach((w) => {
      times.push(w.start, w.end);
    });
    Object.values(solution.timings).forEach((t) => {
      times.push(t.press_start, t.press_end);
      if (t.flash_start != null) times.push(t.flash_start);
      if (t.flash_end != null) times.push(t.flash_end);
    });
    return buildScale(times, innerW);
  }, [input, solution, innerW]);

  const layersById = new Map(input.layers.map((l) => [l.id, l]));

  const ticks = useMemo(() => {
    const span = scale.tMax - scale.tMin;
    const rawStep = span / 10;
    const mag = Math.pow(10, Math.floor(Math.log10(rawStep)));
    const step = mag * (rawStep / mag >= 5 ? 5 : rawStep / mag >= 2 ? 2 : 1);
    const out: number[] = [];
    for (let t = Math.ceil(scale.tMin / step) * step; t <= scale.tMax; t += step) {
      out.push(Math.round(t * 1000) / 1000);
    }
    return out;
  }, [scale]);

  const pressY = 0;
  void pressY;
  const ovenY = 56;

  const edges = useMemo(
    () => dependencyEdges(input.layers, solution.timings, scale, 0),
    [input.layers, solution.timings, scale],
  );

  // 窗口余量弧线：闪干结束 -> 窗口后继刮印开始。
  const windowArcs = input.layers
    .filter((l) => l.window_successor != null)
    .map((l) => {
      const f = solution.timings[String(l.id)];
      const s = solution.timings[String(l.window_successor)];
      if (!f?.flash_end || !s) return null;
      return {
        key: `w${l.id}`,
        x: (xOf(scale, f.flash_end) + xOf(scale, s.press_start)) / 2,
        y: ovenY + 44,
        label: `等待${fmt(s.press_start - f.flash_end)}/[${fmt(l.wait_min)},${fmt(
          l.wait_max,
        )}] 余量${fmt(f.window_slack ?? 0)}`,
      };
    })
    .filter((a): a is { key: string; x: number; y: number; label: string } => a !== null);

  return (
    <div className="timeline-wrap" style={{ width }}>
      {/* 印台轨 */}
      <div className="track-row">
        <div className="track-label">印台</div>
        <div className="track-area">
          <div className="track">
            {input.press_windows.map((w, i) => (
              <div
                key={`pw${i}`}
                className="window-band"
                style={{
                  left: xOf(scale, w.start),
                  width: widthOf(scale, w.start, w.end),
                }}
              />
            ))}
            {solution.print_sequence.map((id, k) => {
              const t = solution.timings[String(id)];
              const layer = layersById.get(id);
              return (
                <div
                  key={`p${id}`}
                  className={`block press ${layer?.wet_group ? "wet" : ""}`}
                  title={`图层 ${id}：刮印 [${fmt(t.press_start)}, ${fmt(t.press_end)})（序列第 ${k + 1} 位）`}
                  style={{
                    left: xOf(scale, t.press_start),
                    width: widthOf(scale, t.press_start, t.press_end),
                  }}
                >
                  {id}
                </div>
              );
            })}
            <svg className="edge-layer" width={innerW} height={120}>
              {edges.map((e) => (
                <path
                  key={e.key}
                  d={e.d}
                  fill="none"
                  stroke={e.wet ? "#a855f7" : "#7aa7d9"}
                  strokeWidth={e.wet ? 2 : 1.2}
                  strokeDasharray={e.wet ? "0" : "4 3"}
                />
              ))}
            </svg>
          </div>
        </div>
      </div>

      {/* 烘台轨 */}
      <div className="track-row">
        <div className="track-label">烘台</div>
        <div className="track-area">
          <div className="track" style={{ marginBottom: 26 }}>
            {input.oven_windows.map((w, i) => (
              <div
                key={`ow${i}`}
                className="window-band"
                style={{
                  left: xOf(scale, w.start),
                  width: widthOf(scale, w.start, w.end),
                }}
              />
            ))}
            {Object.values(solution.timings)
              .filter((t) => t.flash_start != null)
              .map((t) => {
                const fs = t.flash_start as number;
                const fe = t.flash_end as number;
                return (
                <div
                  key={`f${t.layer_id}`}
                  className="block oven"
                  title={`图层 ${t.layer_id}：闪干 [${fmt(fs)}, ${fmt(fe)})`}
                  style={{
                    left: xOf(scale, fs),
                    width: widthOf(scale, fs, fe),
                  }}
                >
                  {t.layer_id}
                </div>
                );
              })}
            {windowArcs.map((a) => (
              <div key={a.key} className="window-arc" style={{ left: a.x, top: a.y }}>
                ▲ {a.label}
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* 时间刻度 */}
      <div className="axis-ticks" style={{ width: innerW, marginLeft: LABEL_W }}>
        {ticks.map((t) => (
          <div key={t} className="tick" style={{ left: xOf(scale, t) }}>
            {fmt(t)}
          </div>
        ))}
      </div>
      <div style={{ marginLeft: LABEL_W }}>
        <span className="tag">
          蓝块=刮印，橙块=闪干；紫框=湿碰湿层；虚线=前驱依赖（紫实线=湿碰湿首尾相接）；
          ▲=复涂窗口等待与余量
        </span>
      </div>
    </div>
  );
}
