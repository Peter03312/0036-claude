import { describe, expect, it } from "vitest";
import { buildScale, fmt, widthOf, xOf } from "./timeline";

describe("timeline geometry", () => {
  it("maps time bounds to pixel width", () => {
    const s = buildScale([0, 10], 108, 8);
    expect(xOf(s, 0)).toBe(8);
    expect(xOf(s, 10)).toBeCloseTo(100);
    expect(widthOf(s, 2, 5)).toBeCloseTo(27.6, 1);
  });

  it("always covers zero and handles equal bounds", () => {
    const s = buildScale([3, 3], 50);
    expect(s.tMin).toBeLessThanOrEqual(0);
    expect(Number.isFinite(s.pxPerUnit)).toBe(true);
  });

  it("fmt trims float noise", () => {
    expect(fmt(1.0000001)).toBe("1");
    expect(fmt(2.3456)).toBe("2.346");
  });
});
