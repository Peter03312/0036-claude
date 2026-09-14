import { describe, expect, it } from "vitest";
import { LocalParseError, parseLayersJson, parseWindowsCsv } from "./parse";

describe("parseLayersJson", () => {
  it("parses a valid layer array", () => {
    const layers = parseLayersJson(
      JSON.stringify([{ id: 1, duration: 3, predecessors: [] }]),
    );
    expect(layers[0].id).toBe(1);
    expect(layers[0].wait_max).toBe(0);
  });

  it("rejects duplicate ids with location", () => {
    expect(() =>
      parseLayersJson(JSON.stringify([{ id: 1 }, { id: 1 }])),
    ).toThrow(LocalParseError);
  });

  it("rejects non-positive duration", () => {
    try {
      parseLayersJson(JSON.stringify([{ id: 1, duration: 0 }]));
      throw new Error("应抛错");
    } catch (e) {
      expect((e as LocalParseError).location).toContain("layers.json[0]");
    }
  });
});

describe("parseWindowsCsv", () => {
  it("parses and sorts windows", () => {
    const ws = parseWindowsCsv("start,end\n10,20\n0,8", "press.csv");
    expect(ws[0]).toEqual({ start: 0, end: 8 });
    expect(ws[1]).toEqual({ start: 10, end: 20 });
  });

  it("locates a bad numeric row", () => {
    try {
      parseWindowsCsv("start,end\n0,x", "press.csv");
      throw new Error("应抛错");
    } catch (e) {
      expect((e as LocalParseError).location).toBe("press.csv 第 2 行");
    }
  });
});
