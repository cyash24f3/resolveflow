import hmac
import time
from pathlib import Path
from uuid import uuid4

from fastapi import Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import Field, field_validator
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from resolveflow.agent.workflow import final_for
from resolveflow.api.auth import ROLES, identity, session_payload, signer
from resolveflow.approvals.service import decide, scoped_run
from resolveflow.domain.common import DomainError, canonical, instant
from resolveflow.domain.policy import authorized_order
from resolveflow.jobs.queue import TERMINAL, enqueue, event
from resolveflow.settings import get_settings
from resolveflow.storage.db import sessions
from resolveflow.storage.models import (
    Case,
    Customer,
    Effect,
    Event,
    Job,
    Order,
    Policy,
    Proposal,
    Run,
    record,
)
from resolveflow.tools.contracts import Strict

WEB = Path(__file__).parents[1] / "web"
TEMPLATES = Environment(loader=FileSystemLoader(WEB), autoescape=select_autoescape(["html"]))
app = FastAPI(title="ResolveFlow · Simulated Support Operations", version="0.1.0")
app.mount("/static", StaticFiles(directory=WEB), name="static")


@app.middleware("http")
async def request_context(request: Request, call_next):
    request.state.request_id = str(uuid4())
    if (
        request.headers.get("content-length", "0").isdigit()
        and int(request.headers.get("content-length", "0")) > 16384
    ):
        return JSONResponse(
            {
                "error": {"code": "invalid_arguments", "message": "Request too large"},
                "request_id": request.state.request_id,
            },
            status_code=413,
        )
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'self'"
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(DomainError)
def domain_error(request, exc):
    return JSONResponse(
        {
            "error": {"code": exc.code, "message": exc.message},
            "request_id": request.state.request_id,
        },
        status_code=exc.status,
    )


@app.exception_handler(RequestValidationError)
def invalid_request(request, exc):
    return JSONResponse(
        {
            "error": {"code": "invalid_arguments", "message": "Request does not match the schema"},
            "request_id": request.state.request_id,
        },
        status_code=422,
    )


@app.get("/", response_class=HTMLResponse)
def index():
    return TEMPLATES.get_template("index.html").render()


@app.get("/api/v1/health")
def health():
    return {"status": "ok", "simulated": True}


@app.get("/api/v1/ready")
def ready():
    try:
        with sessions()() as s:
            s.execute(text("SELECT 1 FROM checkpoints LIMIT 1"))
            seeded = s.get(Customer, "C-100") is not None
        if not seeded:
            raise DomainError("unavailable", "Sandbox is not initialized", 503)
    except DomainError:
        raise
    except Exception as exc:
        raise DomainError("unavailable", "Database/checkpointer is unavailable", 503) from exc
    return {
        "status": "ready",
        "database": "available",
        "checkpointer": "available",
        "provider": "configured_unverified" if get_settings().provider_enabled else "disabled",
        "demo_mode": get_settings().demo_mode,
    }


class Login(Strict):
    role: str = Field(pattern="^(operator|supervisor|developer)$")
    password: str = Field(min_length=1, max_length=200)


def set_session(role):
    data = session_payload(role)
    response = JSONResponse(
        {
            "role": role,
            "csrf": data["csrf"],
            "customers": ROLES[role],
            "demo": get_settings().demo_mode,
            "provider_enabled": get_settings().provider_enabled,
        }
    )
    response.set_cookie(
        "rf_session",
        signer().dumps(data),
        httponly=True,
        secure=get_settings().cookie_secure,
        samesite="strict",
        max_age=28800,
    )
    return response


@app.post("/api/v1/auth/login")
def login(body: Login):
    cfg = get_settings()
    if cfg.public_read_only:
        raise DomainError("forbidden", "Public mode is read only", 403)
    expected = getattr(cfg, f"{body.role}_password").get_secret_value()
    if not expected or not hmac.compare_digest(expected, body.password):
        time.sleep(0.1)
        raise DomainError("unauthorized", "Invalid credentials", 401)
    return set_session(body.role)


@app.post("/api/v1/auth/demo/{role}")
def demo_login(role: str, request: Request):
    if (
        not get_settings().demo_mode
        or get_settings().public_read_only
        or role not in ROLES
        or (
            request.client
            and request.client.host not in ("127.0.0.1", "::1", "testclient")
            and request.headers.get("host", "").split(":")[0] not in ("localhost", "127.0.0.1")
        )
    ):
        raise DomainError("forbidden", "Isolated local demo is unavailable", 403)
    return set_session(role)


@app.get("/api/v1/auth/me")
def me(request: Request, scope=Depends(identity)):
    data = signer().loads(request.cookies["rf_session"], max_age=28800)
    return {
        "role": scope.role,
        "csrf": data["csrf"],
        "customers": scope.customers,
        "demo": get_settings().demo_mode,
        "provider_enabled": get_settings().provider_enabled,
    }


@app.post("/api/v1/auth/logout")
def logout(scope=Depends(identity)):
    response = JSONResponse({"ok": True})
    response.delete_cookie("rf_session")
    return response


class Facts(Strict):
    order_id: str | None = Field(None, min_length=1, max_length=100)
    damage_description: str | None = Field(None, min_length=1, max_length=1000)
    damage_reported_at: str | None = None
    photo_reviewed: bool | None = None
    action: str | None = Field(None, pattern="^(refund|replacement|cancellation|escalation)$")
    amount_minor: int | None = Field(None, ge=0, le=100000000)
    quantity: int | None = Field(None, ge=0, le=100)
    currency: str | None = Field(None, pattern="^[A-Z]{3}$")

    @field_validator("damage_reported_at")
    @classmethod
    def timestamp(cls, value):
        return instant(value).isoformat() if value else value


class CreateRun(Strict):
    customer_id: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=4000)
    mode: str = Field("fixture", pattern="^(fixture|baseline|provider)$")
    idempotency_key: str = Field(min_length=8, max_length=100)
    facts: Facts = Field(default_factory=Facts)


def public_run(s, run):
    effects = list(s.scalars(select(Effect).where(Effect.run_id == run.id)))
    result = {
        k: v for k, v in record(run).items() if k not in ("request_hash", "state", "request_key")
    }
    result["committed_effects"] = [record(e) for e in effects]
    result["next_actions"] = {
        "awaiting_information": ["clarify", "cancel"],
        "awaiting_approval": ["review", "cancel"],
        "queued": ["cancel"],
        "running": ["cancel"],
        "recovering": ["cancel"],
        "failed": ["retry"],
    }.get(run.status, [])
    result["timing"] = {
        "active_seconds": run.state.get("active_seconds"),
        "tool_calls": run.state.get("tool_calls", 0),
        "model_calls": run.state.get("model_calls", 0),
        "tokens": run.state.get("total_tokens") if run.state.get("token_usage_known") else None,
    }
    return result


@app.post("/api/v1/runs", status_code=201)
def create_run(body: CreateRun, scope=Depends(identity)):
    scope.customer(body.customer_id)
    if body.mode == "provider" and not get_settings().provider_enabled:
        raise DomainError(
            "provider_unavailable",
            "Configure a free/local provider before selecting live mode",
            503,
        )
    payload = body.model_dump(exclude={"idempotency_key"})
    hash_ = canonical(payload)
    factory = sessions()
    try:
        with factory.begin() as s:
            existing = s.scalar(
                select(Run).where(
                    Run.workspace == scope.workspace,
                    Run.actor == scope.actor,
                    Run.request_key == body.idempotency_key,
                )
            )
            if existing:
                if existing.request_hash != hash_:
                    raise DomainError("conflict", "Idempotency key reused with a different request")
                return public_run(s, existing)
            customer = s.get(Customer, body.customer_id)
            if not customer or customer.workspace != scope.workspace:
                raise DomainError("not_found", "Customer not found", 404)
            run = Run(
                workspace=scope.workspace,
                actor=scope.actor,
                customer_id=body.customer_id,
                request_key=body.idempotency_key,
                request_hash=hash_,
                request=body.message,
                mode=body.mode,
                facts=body.facts.model_dump(exclude_none=True),
                state={},
            )
            s.add(run)
            s.flush()
            enqueue(s, run)
            event(s, run.id, "submitted", {"mode": run.mode, "simulated": True})
            return public_run(s, run)
    except IntegrityError:
        with factory() as s:
            existing = s.scalar(
                select(Run).where(
                    Run.workspace == scope.workspace,
                    Run.actor == scope.actor,
                    Run.request_key == body.idempotency_key,
                )
            )
            if existing and existing.request_hash == hash_:
                return public_run(s, existing)
        raise DomainError("conflict", "Conflicting concurrent submission") from None


@app.get("/api/v1/runs")
def list_runs(
    limit: int = Query(30, ge=1, le=100), offset: int = Query(0, ge=0), scope=Depends(identity)
):
    with sessions()() as s:
        runs = s.scalars(
            select(Run)
            .where(Run.workspace == scope.workspace, Run.customer_id.in_(scope.customers))
            .order_by(Run.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return {"items": [public_run(s, r) for r in runs], "limit": limit, "offset": offset}


@app.get("/api/v1/runs/{run_id}")
def inspect_run(run_id: str, scope=Depends(identity)):
    with sessions()() as s:
        run = scoped_run(s, scope, run_id)
        result = public_run(s, run)
        result["observations"] = run.state.get("observations", [])
        result["proposal"] = record(s.get(Proposal, run.proposal_id)) if run.proposal_id else None
        result["cases"] = [record(c) for c in s.scalars(select(Case).where(Case.run_id == run.id))]
        return result


@app.get("/api/v1/runs/{run_id}/events")
def events(
    run_id: str,
    after: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    scope=Depends(identity),
):
    with sessions()() as s:
        scoped_run(s, scope, run_id)
        rows = list(
            s.scalars(
                select(Event)
                .where(Event.run_id == run_id, Event.id > after)
                .order_by(Event.id)
                .limit(limit)
            )
        )
        return {
            "items": [
                {
                    "id": e.id,
                    "kind": e.kind,
                    "created_at": e.created_at.isoformat(),
                    "data": e.data
                    if e.kind not in ("tool_result", "provider_call")
                    else {"name": e.data.get("name"), "code": e.data.get("code")},
                }
                for e in rows
            ],
            "next_cursor": rows[-1].id if rows else after,
        }


@app.get("/api/v1/runs/{run_id}/trace")
def trace(run_id: str, scope=Depends(identity)):
    scope.require("developer")
    with sessions()() as s:
        run = scoped_run(s, scope, run_id)
        return {
            "mode": run.mode,
            "state": run.state,
            "events": [
                record(e)
                for e in s.scalars(select(Event).where(Event.run_id == run.id).order_by(Event.id))
            ],
        }


class Clarify(Strict):
    facts: Facts
    idempotency_key: str = Field(min_length=8, max_length=100)


@app.post("/api/v1/runs/{run_id}/clarification")
def clarify(run_id: str, body: Clarify, scope=Depends(identity)):
    from resolveflow.storage.models import Operation

    with sessions().begin() as s:
        run = scoped_run(s, scope, run_id, lock=True)
        op_id = f"clarify:{run.id}:{body.idempotency_key}"
        hash_ = canonical(body.facts.model_dump(exclude_none=True))
        prior = s.get(Operation, op_id)
        if prior:
            if prior.request_hash != hash_:
                raise DomainError("conflict", "Clarification key changed payload")
            return public_run(s, run)
        if run.status != "awaiting_information" or not run.clarification:
            raise DomainError("conflict", "Run is not awaiting information")
        supplied = body.facts.model_dump(exclude_none=True)
        required = set(run.clarification["fields"])
        if not supplied or not set(supplied).issubset(required):
            raise DomainError("invalid_arguments", "Supply only the requested facts", 422)
        run.facts = {**run.facts, **supplied}
        run.clarification = None
        s.add(
            Operation(
                id=op_id,
                run_id=run.id,
                workspace=scope.workspace,
                request_hash=hash_,
                kind="clarification",
                result={"accepted": True},
            )
        )
        event(s, run.id, "clarification_received", {"fields": list(supplied)})
        enqueue(s, run)
        return public_run(s, run)


class Decision(Strict):
    decision: str = Field(pattern="^(approve|reject)$")
    expected_revision: int = Field(ge=1)
    expected_hash: str = Field(pattern="^[a-f0-9]{64}$")


@app.post("/api/v1/proposals/{proposal_id}/decision")
def approval(proposal_id: str, body: Decision, scope=Depends(identity)):
    with sessions().begin() as s:
        value = decide(
            s, scope, proposal_id, body.decision, body.expected_revision, body.expected_hash
        )
        s.flush()
        return record(value)


@app.get("/api/v1/proposals")
def proposals(scope=Depends(identity)):
    with sessions()() as s:
        rows = s.scalars(
            select(Proposal)
            .join(Run, Run.id == Proposal.run_id)
            .where(Run.workspace == scope.workspace, Run.customer_id.in_(scope.customers))
            .order_by(Proposal.id)
            .limit(100)
        )
        return {"items": [record(p) for p in rows]}


@app.get("/api/v1/proposals/{proposal_id}")
def proposal_detail(proposal_id: str, scope=Depends(identity)):
    with sessions()() as s:
        p = s.get(Proposal, proposal_id)
        if not p:
            raise DomainError("not_found", "Proposal not found", 404)
        scoped_run(s, scope, p.run_id)
        return record(p)


@app.post("/api/v1/runs/{run_id}/cancel")
def cancel(run_id: str, scope=Depends(identity)):
    with sessions().begin() as s:
        run = scoped_run(s, scope, run_id, lock=True)
        if run.status in TERMINAL:
            if run.status == "cancelled":
                return public_run(s, run)
            raise DomainError("conflict", "Run is already terminal")
        job = s.scalar(select(Job).where(Job.run_id == run.id).with_for_update())
        run.status, job.status, job.owner = "cancelled", "completed", None
        run.final = final_for(
            s,
            run,
            "cancelled",
            "Cancelled. Any previously committed effects remain in the sandbox ledger.",
        )
        event(s, run.id, "cancelled", {})
        return public_run(s, run)


@app.post("/api/v1/runs/{run_id}/retry")
def retry(run_id: str, scope=Depends(identity)):
    scope.require("developer")
    with sessions().begin() as s:
        run = scoped_run(s, scope, run_id, lock=True)
        job = s.scalar(select(Job).where(Job.run_id == run.id).with_for_update())
        if (
            run.status != "failed"
            or job.attempts >= get_settings().max_job_attempts
            or job.error not in ("OperationalError", "provider_unavailable", "transient_failure")
        ):
            raise DomainError("conflict", "This failure is not eligible for retry")
        enqueue(s, run)
        return public_run(s, run)


@app.get("/api/v1/sandbox")
def sandbox(scope=Depends(identity)):
    with sessions()() as s:
        run_ids = select(Run.id).where(
            Run.workspace == scope.workspace, Run.customer_id.in_(scope.customers)
        )
        return {
            "customers": [
                record(c)
                for c in s.scalars(
                    select(Customer).where(
                        Customer.workspace == scope.workspace, Customer.id.in_(scope.customers)
                    )
                )
            ],
            "orders": [
                record(o)
                for o in s.scalars(
                    select(Order).where(
                        Order.workspace == scope.workspace, Order.customer_id.in_(scope.customers)
                    )
                )
            ],
            "cases": [record(c) for c in s.scalars(select(Case).where(Case.run_id.in_(run_ids)))],
            "effects": [
                record(e) for e in s.scalars(select(Effect).where(Effect.run_id.in_(run_ids)))
            ],
            "policies": [record(p) for p in s.scalars(select(Policy))],
            "simulated": True,
        }


@app.get("/api/v1/sandbox/orders/{order_id}")
def order_detail(order_id: str, scope=Depends(identity)):
    with sessions()() as s:
        return record(authorized_order(s, scope, order_id))


@app.get("/api/v1/cases/{case_id}")
def case_detail(case_id: str, scope=Depends(identity)):
    with sessions()() as s:
        case = s.get(Case, case_id)
        if not case:
            raise DomainError("not_found", "Case not found", 404)
        scoped_run(s, scope, case.run_id)
        return record(case)


@app.get("/api/v1/evaluations")
def evaluations(scope=Depends(identity)):
    scope.require("developer")
    import json

    path = Path("docs/evidence/evaluation.json")
    return {
        "items": [json.loads(path.read_text())] if path.exists() else [],
        "note": "Fixture results are plumbing evidence. Semantic human review and live-provider quality are separate.",
    }


@app.get("/api/v1/metrics")
def metrics(scope=Depends(identity)):
    scope.require("developer")
    with sessions()() as s:
        ids = select(Run.id).where(
            Run.workspace == scope.workspace, Run.customer_id.in_(scope.customers)
        )
        return {
            "queue": {
                status: count
                for status, count in s.execute(
                    select(Job.status, func.count()).where(Job.run_id.in_(ids)).group_by(Job.status)
                )
            },
            "runs": {
                status: count
                for status, count in s.execute(
                    select(Run.status, func.count()).where(Run.id.in_(ids)).group_by(Run.status)
                )
            },
            "events": {
                kind: count
                for kind, count in s.execute(
                    select(Event.kind, func.count())
                    .where(Event.run_id.in_(ids))
                    .group_by(Event.kind)
                )
            },
        }


@app.get("/api/v1/sample")
def sample():
    return {
        "read_only": True,
        "mode": "fixture",
        "fictional": True,
        "example": {
            "request": "My lamp arrived damaged",
            "steps": [
                "inspect assigned order",
                "check policy",
                "collect damage evidence",
                "propose replacement",
                "supervisor approval",
                "simulated ledger effect",
            ],
        },
    }
