"""套印编排台后端。

路由
----
GET  /api/health                  健康检查
POST /api/parse                   上传 layers JSON + 两台 CSV，返回规范化输入
POST /api/schedule                编排（JSON body，可带固定位置）
POST /api/schedule/upload         编排（multipart 上传文件）
POST /api/adopt                   采纳：冻结输入与工艺单为快照
GET  /api/sample                  返回内置示例输入
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .diagnostics import diagnose
from .models import (
    AdoptSnapshot,
    Conflict,
    ErrorResponse,
    FixPosition,
    ScheduleRequest,
    ScheduleSolution,
)
from .parser import InputError, parse_layers_json, parse_windows_csv, static_validate
from .scheduler import Fix, search
from . import samples

app = FastAPI(title="丝网套印编排台", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/sample")
def sample() -> dict:
    return samples.greedy_miss_sample()


def _read_upload(f: UploadFile) -> bytes:
    data = f.file.read()
    if not data.strip():
        raise InputError("上传文件为空", f.filename)
    return data


def _build_input(layers_raw: bytes, press_raw: bytes, oven_raw: bytes):
    layers = parse_layers_json(layers_raw)
    press = parse_windows_csv(press_raw, "press.csv")
    oven = parse_windows_csv(oven_raw, "oven.csv")
    from .models import ScheduleInput

    inp = ScheduleInput(layers=layers, press_windows=press, oven_windows=oven)
    report = static_validate(inp)
    return inp, report.conflicts


def _fail(conflicts: list[Conflict]) -> JSONResponse:
    return JSONResponse(
        status_code=200,
        content=ErrorResponse(feasible=False, conflicts=conflicts).model_dump(),
    )


def _run(inp, fix_positions: list[FixPosition]):
    report = static_validate(inp)
    if report.conflicts:
        return _fail(report.conflicts)

    # 固定位置合法性（编号存在、位置范围、不重复）在 scheduler 内部也会判，
    # 这里给出更可读的错误。
    ids = {l.id for l in inp.layers}
    n = len(inp.layers)
    pos_seen: set[int] = set()
    layer_seen: set[int] = set()
    for fx in fix_positions:
        if fx.layer_id not in ids:
            return _fail(
                [
                    Conflict(
                        type="FIX_UNKNOWN_LAYER",
                        message=f"固定位置引用的图层 {fx.layer_id} 不存在",
                        layers=[fx.layer_id],
                    )
                ]
            )
        if not 1 <= fx.position <= n:
            return _fail(
                [
                    Conflict(
                        type="FIX_POSITION_OUT_OF_RANGE",
                        message=f"图层 {fx.layer_id} 的固定位置 {fx.position} 超出 1..{n}",
                        layers=[fx.layer_id],
                    )
                ]
            )
        if fx.position in pos_seen or fx.layer_id in layer_seen:
            return _fail(
                [
                    Conflict(
                        type="FIX_POSITION_CONFLICT",
                        message=f"图层 {fx.layer_id} 的固定位置与其他固定项冲突",
                        layers=[fx.layer_id],
                    )
                ]
            )
        pos_seen.add(fx.position)
        layer_seen.add(fx.layer_id)

    fixes = [Fix(layer_id=fx.layer_id, position=fx.position) for fx in fix_positions]
    sol = search(inp, fixes)
    if sol is not None:
        return JSONResponse(status_code=200, content=sol.model_dump())
    return _fail(diagnose(inp, fixes))


@app.post("/api/schedule")
def schedule_endpoint(req: ScheduleRequest):
    return _run(req.input, req.fix_positions)


@app.post("/api/schedule/upload")
async def schedule_upload(
    layers: UploadFile = File(...),
    press: UploadFile = File(...),
    oven: UploadFile = File(...),
    fix_positions: str = Form("[]"),
):
    try:
        layers_raw = _read_upload(layers)
        press_raw = _read_upload(press)
        oven_raw = _read_upload(oven)
        inp, conflicts = _build_input(layers_raw, press_raw, oven_raw)
        try:
            raw_fixes = json.loads(fix_positions)
            fix_list = [FixPosition.model_validate(x) for x in raw_fixes]
        except Exception as exc:
            raise InputError(f"fix_positions 解析失败：{exc}", "form")
    except InputError as exc:
        raise HTTPException(status_code=422, detail={"location": exc.location, "message": exc.message})
    if conflicts:
        return _fail(conflicts)
    return _run(inp, fix_list)


@app.post("/api/parse")
async def parse_endpoint(
    layers: UploadFile = File(...),
    press: UploadFile = File(...),
    oven: UploadFile = File(...),
):
    try:
        inp, conflicts = _build_input(
            _read_upload(layers), _read_upload(press), _read_upload(oven)
        )
    except InputError as exc:
        raise HTTPException(
            status_code=422, detail={"location": exc.location, "message": exc.message}
        )
    return {"input": inp.model_dump(), "static_conflicts": [c.model_dump() for c in conflicts]}


@app.post("/api/adopt")
def adopt(req: ScheduleRequest):
    """采纳：只有存在可行解时才冻结为可重开的工艺单。

    与 /api/schedule 走同一套静态校验、完整搜索与无解诊断；若输入非法或无解，
    返回与排程一致的冲突结构（feasible=false），HTTP 409，绝不冻结。
    """
    result = _run(req.input, req.fix_positions)
    # _run 对有解/无解均返回 JSONResponse。
    if isinstance(result, JSONResponse) and result.status_code == 200:
        body = json.loads(result.body)
        if body.get("feasible") is True:
            snapshot = AdoptSnapshot(
                version=1,
                request=req,
                solution=ScheduleSolution.model_validate(body),
                adopted_at=datetime.now(timezone.utc).isoformat(),
            )
            return snapshot.model_dump()
    # 无解或非法：透传冲突（状态码置 409）。
    if isinstance(result, JSONResponse):
        result.status_code = 409
        return result
    return result


@app.exception_handler(InputError)
def input_error_handler(_request, exc: InputError):  # pragma: no cover
    return JSONResponse(
        status_code=422,
        content={"location": exc.location, "message": exc.message},
    )
