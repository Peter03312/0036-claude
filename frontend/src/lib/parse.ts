// 本地解析图层 JSON 与设备时段 CSV（上传前即可预览；错误定位与后端一致）。
import type { Interval, Layer } from "./types";

export class LocalParseError extends Error {
  constructor(
    public location: string,
    message: string,
  ) {
    super(message);
  }
}

export function parseLayersJson(text: string): Layer[] {
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch (e) {
    const err = e as SyntaxError & { lineNumber?: number; columnNumber?: number };
    throw new LocalParseError(
      "layers.json",
      `JSON 解析失败：${err.message}`,
    );
  }
  if (typeof data === "object" && data !== null && "layers" in data) {
    data = (data as { layers: unknown }).layers;
  }
  if (!Array.isArray(data)) {
    throw new LocalParseError("layers.json", "顶层必须是数组或含 layers 的对象");
  }
  if (data.length === 0) throw new LocalParseError("layers.json", "图层列表为空");

  const layers: Layer[] = [];
  const seen = new Set<number>();
  data.forEach((raw, i) => {
    const loc = `layers.json[${i}]`;
    if (typeof raw !== "object" || raw === null) {
      throw new LocalParseError(loc, "每个图层必须是对象");
    }
    const o = raw as Record<string, unknown>;
    const requireNum = (key: string, { positive = false } = {}): number => {
      const v = o[key];
      if (typeof v !== "number" || !Number.isFinite(v)) {
        throw new LocalParseError(loc, `字段 ${key} 必须是数值`);
      }
      if (positive && v <= 0) throw new LocalParseError(loc, `字段 ${key} 必须为正`);
      return v;
    };
    if (typeof o.id !== "number" || !Number.isInteger(o.id)) {
      throw new LocalParseError(loc, "字段 id 必须是唯一整数");
    }
    if (seen.has(o.id)) throw new LocalParseError(loc, `图层编号 ${o.id} 重复`);
    seen.add(o.id);

    const duration = requireNum("duration", { positive: true });
    const flash = o.flash === true;
    const flashDuration =
      typeof o.flash_duration === "number" ? o.flash_duration : 0;
    const windowSuccessor =
      typeof o.window_successor === "number" ? o.window_successor : null;
    const layer: Layer = {
      id: o.id,
      duration,
      predecessors: Array.isArray(o.predecessors)
        ? (o.predecessors as number[])
        : [],
      wet_group: typeof o.wet_group === "string" ? o.wet_group : null,
      flash,
      flash_duration: flashDuration,
      window_successor: windowSuccessor,
      wait_min: typeof o.wait_min === "number" ? o.wait_min : 0,
      wait_max: typeof o.wait_max === "number" ? o.wait_max : 0,
    };
    layers.push(layer);
  });
  return layers;
}

export function parseWindowsCsv(text: string, source: string): Interval[] {
  const lines = text.trim().split(/\r?\n/);
  if (lines.length === 0) throw new LocalParseError(source, "CSV 为空");
  const headers = lines[0].split(",").map((h) => h.trim().toLowerCase());
  const si = headers.indexOf("start");
  const ei = headers.indexOf("end");
  if (si === -1 || ei === -1) {
    throw new LocalParseError(source, "表头必须包含 start 与 end 列");
  }
  const out: Interval[] = [];
  for (let r = 1; r < lines.length; r++) {
    const loc = `${source} 第 ${r + 1} 行`;
    const cols = lines[r].split(",");
    const start = Number(cols[si]?.trim());
    const end = Number(cols[ei]?.trim());
    if (!Number.isFinite(start) || !Number.isFinite(end)) {
      throw new LocalParseError(loc, "start/end 必须是数值");
    }
    if (!(end > start)) throw new LocalParseError(loc, "须满足 end > start");
    out.push({ start, end });
  }
  if (out.length === 0) throw new LocalParseError(source, "没有任何可用时段");
  out.sort((a, b) => a.start - b.start);
  return out;
}
