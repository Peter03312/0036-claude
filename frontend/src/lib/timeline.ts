// 时间轴几何计算：把时间区间映射为像素，纯函数便于单测。

export interface AxisScale {
  tMin: number;
  tMax: number;
  pxPerUnit: number;
}

export function buildScale(
  times: number[],
  width: number,
  padding = 8,
): AxisScale {
  const finite = times.filter((t) => Number.isFinite(t));
  const tMin = Math.min(0, ...finite);
  const tMax = Math.max(...finite, 1);
  const span = Math.max(tMax - tMin, 1e-9);
  return { tMin, tMax, pxPerUnit: (width - padding * 2) / span };
}

export function xOf(scale: AxisScale, t: number, padding = 8): number {
  return padding + (t - scale.tMin) * scale.pxPerUnit;
}

export function widthOf(
  scale: AxisScale,
  start: number,
  end: number,
): number {
  return Math.max((end - start) * scale.pxPerUnit, 1);
}

export function fmt(t: number): string {
  // 去掉浮点误差尾差。
  return String(Math.round(t * 1000) / 1000);
}
