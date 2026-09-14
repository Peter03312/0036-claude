"""请求/响应数据模型。

时间一律为非负数值（调用方自行保证单位一致，例如分钟）。
设备区间采用左闭右开 [start, end)。
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, ConfigDict, field_validator


class Layer(BaseModel):
    """一个印刷图层。"""

    model_config = ConfigDict(extra="forbid")

    id: int = Field(..., description="唯一整数编号")
    duration: float = Field(..., gt=0, description="刮印时长，必须为正")
    predecessors: list[int] = Field(default_factory=list, description="前驱图层编号")
    wet_group: Optional[str] = Field(
        default=None, description="湿碰湿组标识；同组在同一印台首尾相接"
    )
    flash: bool = Field(default=False, description="刮印后是否进入烘台闪干")
    flash_duration: float = Field(default=0.0, ge=0, description="闪干时长")
    window_successor: Optional[int] = Field(
        default=None, description="窗口后继编号；仅闪干层可设置"
    )
    wait_min: float = Field(
        default=0.0, ge=0, description="闪干结束到后继刮印开始的最短等待（含）"
    )
    wait_max: float = Field(
        default=0.0, ge=0, description="闪干结束到后继刮印开始的最长等待（含）"
    )


class Interval(BaseModel):
    """设备可用时段，左闭右开。"""

    model_config = ConfigDict(extra="forbid")

    start: float
    end: float


class ScheduleInput(BaseModel):
    """编排输入：图层与两类设备的可用时段。"""

    layers: list[Layer]
    press_windows: list[Interval]
    oven_windows: list[Interval]


class FixPosition(BaseModel):
    """固定某图层在完整刮印序列中（从 1 起）的位置。"""

    model_config = ConfigDict(extra="forbid")

    layer_id: int
    position: int = Field(..., ge=1)


class ScheduleRequest(BaseModel):
    input: ScheduleInput
    fix_positions: list[FixPosition] = Field(default_factory=list)


class LayerTiming(BaseModel):
    layer_id: int
    press_start: float
    press_end: float
    flash_start: Optional[float] = None
    flash_end: Optional[float] = None
    window_slack: Optional[float] = Field(
        default=None, description="后继实际等待相对最长等待的余量；无窗口后继为 null"
    )
    window_wait: Optional[float] = Field(
        default=None, description="闪干结束到窗口后继刮印开始的实际等待"
    )


class ScheduleSolution(BaseModel):
    feasible: bool = True
    makespan: float
    window_wait_sum: float
    print_sequence: list[int]
    press_starts: list[float]
    flash_starts: list[Optional[float]]
    timings: dict[int, LayerTiming]

    @field_validator("timings", mode="before")
    @classmethod
    def _normalize_timing_keys(cls, value):
        # JSON 往返后字典键会变成字符串，这里归一回整数。
        if isinstance(value, dict):
            return {int(k): v for k, v in value.items()}
        return value


class Conflict(BaseModel):
    type: str = Field(..., description="冲突约束类型标识")
    message: str
    layers: list[int] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    feasible: bool = False
    conflicts: list[Conflict]


class AdoptSnapshot(BaseModel):
    """采纳后冻结的工艺单快照，可原样重开。"""

    version: int = 1
    request: ScheduleRequest
    solution: ScheduleSolution
    adopted_at: str
