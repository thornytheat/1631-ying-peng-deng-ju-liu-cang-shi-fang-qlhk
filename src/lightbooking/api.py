from dataclasses import asdict
from functools import lru_cache
import json
import os
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from .checkout_reconcile.service import compare_records, evidence, export_table
from .hold_registry.contracts import RevisionConflict, UnknownRelease
from .hold_registry.history import release_changes
from .hold_registry.service import list_releases, read_release, register
from .engine import ROOT, plan
from .settings import DEFAULT_BUDGET, DEFAULT_DAY, MODEL_LABEL, PROJECT_NAME

app = FastAPI(title=PROJECT_NAME, version="1.0.0")
app.mount("/static", StaticFiles(directory=ROOT / "web"), name="static")


@app.get("/", include_in_schema=False)
def workbench():
    return FileResponse(ROOT / "web" / "index.html")


SECTIONS = {
    "lighting_holds": "ingestion",
    "booking_signals": "features",
    "rental_hist_bayes": "model",
    "shoot_holdout": "replay",
    "client_mix": "shift",
    "gear_reuse": "resources",
}
Capacity = Annotated[int, Query(ge=0, le=100)]
Snapshot = Annotated[int, Query(ge=70, le=36_500)]


class Feed(BaseModel):
    model_config = ConfigDict(extra="forbid")
    observations: list = Field(max_length=2500)
    outcomes: list = Field(max_length=2500)


class PlanInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    capacity: StrictInt = Field(default=DEFAULT_BUDGET, ge=0, le=100)
    as_of: StrictInt = Field(default=DEFAULT_DAY, ge=70, le=36_500)
    packet: Feed | None = None


class RegisterInput(PlanInput):
    expected_generation: StrictInt = Field(ge=0)
    run_id: str = Field(pattern=r"^[0-9a-f]{64}$")


def store():
    return Path(os.environ.get("WORKSHOP_DB", ROOT / "var" / "register.sqlite3"))


@app.middleware("http")
async def constrain_payload(request: Request, call_next):
    if request.method == "POST":
        declared = request.headers.get("content-length", "")
        if declared.isdecimal() and int(declared) > 2_000_000:
            return JSONResponse({"detail": "单次批次上限 2 MB"}, status_code=413)
    return await call_next(request)


@lru_cache(maxsize=24)
def sample_plan(capacity, as_of):
    return plan(as_of=as_of, capacity=capacity)


def compute(command: PlanInput):
    try:
        if command.packet is None:
            return sample_plan(command.capacity, command.as_of)
        return plan(
            command.packet.model_dump(), as_of=command.as_of, capacity=command.capacity
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/healthz")
def health():
    body = {
        "status": "ready",
        "service": PROJECT_NAME,
        "model": MODEL_LABEL,
        "default_snapshot": DEFAULT_DAY,
        "run_endpoint": "/api/plan",
        "summary_endpoint": "/api/summary",
    }
    return Response(
        json.dumps(body, ensure_ascii=False, indent=2), media_type="application/json"
    )


@app.get("/api/plan")
def trial(capacity: Capacity = DEFAULT_BUDGET, as_of: Snapshot = DEFAULT_DAY):
    return sample_plan(capacity, as_of).body


@app.post("/api/plan")
def custom_trial(command: PlanInput):
    return compute(command).body


@app.get("/api/summary")
def summary(capacity: Capacity = DEFAULT_BUDGET):
    report = sample_plan(capacity, DEFAULT_DAY).body
    return {
        "project": report["project"],
        "action": report["action"],
        "intake": report["intake"]["incoming"],
        "exceptions": report["intake"]["reasons"],
        "estimator": report["model"]["algorithm"],
        "metric": report["evaluation"]["metric"],
        "holdout": report["evaluation"]["holdout_cases"],
        "report": report["summary"],
        "first_allocations": [
            row for row in report["decisions"] if row["status"] == "allocated"
        ][:5],
    }


@app.get("/api/modules/{module}")
def module_evidence(module: str, capacity: Capacity = DEFAULT_BUDGET):
    if module not in SECTIONS:
        raise HTTPException(404, "模块不存在")
    report = sample_plan(capacity, DEFAULT_DAY).body
    return {
        "module": module,
        "run_id": report["run_id"],
        "evidence": evidence(report, SECTIONS[module]),
    }


@app.get("/api/decisions/{case_id}")
def single(case_id: str, capacity: Capacity = DEFAULT_BUDGET):
    report = sample_plan(capacity, DEFAULT_DAY).body
    entry = report["row_evidence"].get(case_id)
    if entry is None:
        raise HTTPException(404, "候选单据不存在")
    return {
        "decision": next(
            item for item in report["decisions"] if item["case_id"] == case_id
        ),
        "input_evidence": entry,
    }


@app.get("/api/compare")
def compare(capacity: Capacity = DEFAULT_BUDGET, against: Capacity = 0):
    result = sample_plan(capacity, DEFAULT_DAY).body
    reference = sample_plan(against, DEFAULT_DAY).body
    return {
        "current": result["summary"],
        "reference": reference["summary"],
        "changes": compare_records(result, reference),
    }


@app.get("/api/decisions.csv")
def download(capacity: Capacity = DEFAULT_BUDGET):
    body = sample_plan(capacity, DEFAULT_DAY).body
    return Response(
        "\ufeff" + export_table(body),
        media_type="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=lightbooking-decisions.csv"
        },
    )


@app.get("/api/releases")
def releases(
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    before: Annotated[int | None, Query(gt=0)] = None,
):
    return [asdict(value) for value in list_releases(store(), limit, before)]


@app.get("/api/releases/{generation}")
def archived(generation: int):
    try:
        return asdict(read_release(store(), generation))
    except UnknownRelease as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/release-differences")
def release_diff(
    before: Annotated[int, Query(gt=0)], after: Annotated[int, Query(gt=0)]
):
    try:
        return release_changes(store(), before, after)
    except UnknownRelease as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.post("/api/releases", status_code=201)
def publish(command: RegisterInput):
    delivery = compute(command)
    if not delivery.quantity:
        raise HTTPException(422, "没有可登记的候选单据")
    if delivery.digest != command.run_id:
        raise HTTPException(409, "待登记证据已经变化，请按新方案重新核对")
    try:
        return asdict(register(store(), delivery, command.expected_generation))
    except RevisionConflict as exc:
        raise HTTPException(409, str(exc)) from exc
