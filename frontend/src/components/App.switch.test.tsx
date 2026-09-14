import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import App from "../App";

// 两个不同的示例输入，模拟切换内置示例。
const sampleA = {
  layers: [
    { id: 1, duration: 3, predecessors: [], wet_group: null, flash: true,
      flash_duration: 3, window_successor: 3, wait_min: 0, wait_max: 1 },
    { id: 2, duration: 9, predecessors: [], wet_group: null, flash: true,
      flash_duration: 3, window_successor: null, wait_min: 0, wait_max: 0 },
    { id: 3, duration: 3, predecessors: [1, 2], wet_group: null, flash: false,
      flash_duration: 0, window_successor: null, wait_min: 0, wait_max: 0 },
  ],
  press_windows: [{ start: 0, end: 10 }, { start: 10, end: 19 }],
  oven_windows: [{ start: 0, end: 6 }, { start: 6, end: 46 }],
};

const sampleB = {
  layers: [
    { id: 10, duration: 2, predecessors: [], wet_group: null, flash: false,
      flash_duration: 0, window_successor: null, wait_min: 0, wait_max: 0 },
  ],
  press_windows: [{ start: 0, end: 20 }],
  oven_windows: [{ start: 0, end: 20 }],
};

type Sample = typeof sampleA;

function solutionFor(input: Sample) {
  // 与后端解同构的时序响应：依次串行排，保证时序与图层一致。
  const timings: Record<string, unknown> = {};
  let cursor = 0;
  const pressStarts: number[] = [];
  const flashStarts: (number | null)[] = [];
  for (const l of input.layers) {
    pressStarts.push(cursor);
    timings[String(l.id)] = {
      layer_id: l.id,
      press_start: cursor,
      press_end: cursor + l.duration,
      flash_start: l.flash ? cursor + l.duration : null,
      flash_end: l.flash ? cursor + l.duration + l.flash_duration : null,
      window_slack: null,
      window_wait: null,
    };
    flashStarts.push(l.flash ? cursor + l.duration : null);
    cursor += l.duration + (l.flash ? l.flash_duration : 0);
  }
  return {
    feasible: true,
    makespan: cursor,
    window_wait_sum: 0,
    print_sequence: input.layers.map((l) => l.id),
    press_starts: pressStarts,
    flash_starts: flashStarts,
    timings,
  };
}

describe("App 切换示例不白屏", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("排程后切换到图层不同的内置示例，页面仍正常渲染（旧 result 被清空）", async () => {
    let which: "A" | "B" = "A";
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      const u = String(url);
      if (u.endsWith("/api/sample")) {
        return new Response(JSON.stringify(which === "A" ? sampleA : sampleB), {
          headers: { "Content-Type": "application/json" },
        });
      }
      if (u.endsWith("/api/schedule")) {
        const body = JSON.parse(String(init?.body ?? "{}"));
        return new Response(JSON.stringify(solutionFor(body.input as Sample)), {
          headers: { "Content-Type": "application/json" },
        });
      }
      return new Response("{}", { headers: { "Content-Type": "application/json" } });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    await waitFor(() => {
      if (!screen.queryByText(/完整搜索/)) throw new Error("未载入初始示例");
    });
    expect(screen.queryByText(/已载入 3 个图层/)).toBeTruthy();

    // 运行一次排程，产出 result（双时间轴出现）。
    fireEvent.click(screen.getByText(/^完整搜索 \/ 重算$/));
    await waitFor(() => expect(screen.queryByText(/双时间轴/)).toBeTruthy());

    // 切换到图层集合完全不同的示例 B。
    which = "B";
    fireEvent.click(screen.getByText(/载入内置示例/));

    await waitFor(() => expect(screen.queryByText(/已载入 1 个图层/)).toBeTruthy());
    // 旧时序被清空，标题仍在，页面不白屏。
    expect(screen.queryByText(/双时间轴/)).toBeNull();
    expect(screen.queryByText(/丝网套印编排台/)).toBeTruthy();
  });
});
