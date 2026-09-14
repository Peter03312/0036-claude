import type {
  AdoptSnapshot,
  FixPosition,
  ScheduleInput,
  ScheduleResult,
} from "./types";

export class ApiError extends Error {
  constructor(
    public status: number,
    public location: string | null,
    message: string,
  ) {
    super(message);
  }
}

async function parseError(res: Response): Promise<ApiError> {
  let location: string | null = null;
  let message = `请求失败（HTTP ${res.status}）`;
  try {
    const data = await res.json();
    if (data?.detail) {
      location = data.detail.location ?? null;
      message = data.detail.message ?? message;
    } else if (typeof data?.message === "string") {
      message = data.message;
    }
  } catch {
    /* 忽略非 JSON 错误体 */
  }
  return new ApiError(res.status, location, message);
}

export async function schedule(
  input: ScheduleInput,
  fixPositions: FixPosition[] = [],
): Promise<ScheduleResult> {
  const res = await fetch("/api/schedule", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ input, fix_positions: fixPositions }),
  });
  if (!res.ok) throw await parseError(res);
  return (await res.json()) as ScheduleResult;
}

export async function uploadFiles(
  layers: File,
  press: File,
  oven: File,
): Promise<{ input: ScheduleInput; static_conflicts: unknown[] }> {
  const form = new FormData();
  form.append("layers", layers);
  form.append("press", press);
  form.append("oven", oven);
  const res = await fetch("/api/parse", { method: "POST", body: form });
  if (!res.ok) throw await parseError(res);
  return res.json();
}

export async function adopt(
  input: ScheduleInput,
  fixPositions: FixPosition[],
): Promise<AdoptSnapshot> {
  const res = await fetch("/api/adopt", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ input, fix_positions: fixPositions }),
  });
  if (!res.ok) throw await parseError(res);
  return res.json();
}

export async function fetchSample(): Promise<ScheduleInput> {
  const res = await fetch("/api/sample");
  if (!res.ok) throw await parseError(res);
  return res.json();
}

export function downloadJson(filename: string, data: unknown): void {
  const blob = new Blob([JSON.stringify(data, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
