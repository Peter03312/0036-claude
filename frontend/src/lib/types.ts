// 与后端 app/models.py 对应的类型定义。

export interface Layer {
  id: number;
  duration: number;
  predecessors: number[];
  wet_group: string | null;
  flash: boolean;
  flash_duration: number;
  window_successor: number | null;
  wait_min: number;
  wait_max: number;
}

export interface Interval {
  start: number;
  end: number;
}

export interface ScheduleInput {
  layers: Layer[];
  press_windows: Interval[];
  oven_windows: Interval[];
}

export interface FixPosition {
  layer_id: number;
  position: number;
}

export interface LayerTiming {
  layer_id: number;
  press_start: number;
  press_end: number;
  flash_start: number | null;
  flash_end: number | null;
  window_slack: number | null;
  window_wait: number | null;
}

export interface ScheduleSolution {
  feasible: true;
  makespan: number;
  window_wait_sum: number;
  print_sequence: number[];
  press_starts: number[];
  flash_starts: (number | null)[];
  timings: Record<string, LayerTiming>;
}

export interface Conflict {
  type: string;
  message: string;
  layers: number[];
}

export interface ErrorResponse {
  feasible: false;
  conflicts: Conflict[];
}

export type ScheduleResult = ScheduleSolution | ErrorResponse;

export interface AdoptSnapshot {
  version: number;
  request: { input: ScheduleInput; fix_positions: FixPosition[] };
  solution: ScheduleSolution;
  adopted_at: string;
}

export function isSolution(r: ScheduleResult): r is ScheduleSolution {
  return r.feasible === true;
}
