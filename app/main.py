"""Rawaj Pay transfer API. See README.md for the endpoints, errors and rules."""
import hashlib
import json
import threading
import uuid

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select, update
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.db import make_engine, make_session_factory
from app.models import Account, IdempotencyRecord, Transfer
from app.problems import ProblemError, problem_body, problem_response
from app.ratelimit import TokenBucketLimiter
from app.settings import Settings


                    ### strict=True ya3ni 150.5 w "150" w true kollohom yet-rafedo, w forbid ya3ni ay field zyada 422
class TransferIn(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    from_account_id: str = Field(min_length=1)
    to_account_id: str = Field(min_length=1)
    amount_piastres: int = Field(gt=0)
    memo: str | None = Field(default=None, max_length=140)


def _transfer_json(t: Transfer) -> dict:
    return {
        "id": t.id,
        "from_account_id": t.from_account_id,
        "to_account_id": t.to_account_id,
        "amount_piastres": t.amount_piastres,
        "memo": t.memo,
        "status": t.status,
    }


def _json_response(status: int, body: dict, replayed: bool = False) -> Response:
    media = "application/json" if status < 400 else "application/problem+json"
    return _raw_response(status, json.dumps(body), media, replayed)


def _raw_response(status: int, text: str, media: str, replayed: bool = False) -> Response:
    headers = {"Idempotent-Replayed": "true"} if replayed else {}
    return Response(content=text, status_code=status, media_type=media, headers=headers)


def _body_hash(p: TransferIn) -> str:
                 ### fingerprint lel body, ay far2 (amount, destination, memo) yeghayar el hash
    canonical = json.dumps(p.model_dump(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def create_app(settings: Settings) -> FastAPI:
    app = FastAPI(title="Rawaj Pay transfers")

              ### el engine lazem yetsama app.state.engine (el tests bet-use-ha)
    engine = make_engine(settings.database_url)
    app.state.engine = engine
    app.state.settings = settings
    session_factory = make_session_factory(engine)
    limiter = TokenBucketLimiter(
        settings.rate_limit_capacity, settings.rate_limit_refill_per_second, settings.clock
    )
    write_lock = threading.Lock()           ### nsalsel el transfers 3ashan el balance mayeb2ash negative

    
    @app.exception_handler(ProblemError)
    async def _problem_handler(request: Request, exc: ProblemError):
        return problem_response(exc.status, exc.title, exc.detail, exc.headers, exc.extra)

    @app.exception_handler(StarletteHTTPException)
    async def _http_handler(request: Request, exc: StarletteHTTPException):
        return problem_response(exc.status_code, str(exc.detail), headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(request: Request, exc: RequestValidationError):
        return problem_response(422, "Validation error", extra={"errors": _errors(exc)})

    def current_customer(request: Request) -> str:
        unauthorized = ProblemError(401, "Unauthorized", "Missing or invalid bearer token",
                                    headers={"WWW-Authenticate": "Bearer"})
        header = request.headers.get("authorization")
        if not header:
            raise unauthorized
        parts = header.split(" ", 1)
                          ### lazem "Bearer <token>" bas, Basic/Token/Bearer fady kollohom 401
        if len(parts) != 2 or parts[0].lower() != "bearer":
            raise unauthorized
        token = parts[1].strip()
        customer = settings.api_tokens.get(token) if token else None
        if customer is None:
            raise unauthorized
        return customer

                             ### el rate limit ba3d el auth w abl ay 7aga tanya (hatta abl el Idempotency-Key check)
    def rate_limited_customer(customer: str = Depends(current_customer)) -> str:
        retry_after = limiter.acquire(customer)
        if retry_after:
            raise ProblemError(429, "Too Many Requests", "Rate limit exceeded",
                               headers={"Retry-After": str(retry_after)})
        return customer

    @app.post("/v1/transfers")
    async def create_transfer(request: Request, customer: str = Depends(rate_limited_customer)):
        key = request.headers.get("idempotency-key")
        if not key:
            raise ProblemError(400, "Missing Idempotency-Key", "Send an Idempotency-Key header")

        
        raw = await request.body()
        try:
            data = json.loads(raw)
            payload = TransferIn.model_validate(data)
        except (ValueError, ValidationError) as exc:
            errors = _errors(exc) if isinstance(exc, ValidationError) else None
            raise ProblemError(422, "Validation error", "Invalid request body",
                               extra={"errors": errors} if errors else None)
        if payload.amount_piastres > settings.max_transfer_piastres:
            raise ProblemError(422, "Validation error", "amount_piastres is over the limit")
        if payload.from_account_id == payload.to_account_id:
            raise ProblemError(422, "Validation error", "Source and destination must differ")

        return await run_in_threadpool(_do_transfer, customer, key, payload)

    def _do_transfer(customer: str, key: str, payload: TransferIn) -> Response:
        body_hash = _body_hash(payload)
                        ### el lock + transaction wa7da: lookup, debit, credit, transfer, record kolohom ma3an
        with write_lock, session_factory() as s, s.begin():
            existing = s.scalar(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.customer_id == customer, IdempotencyRecord.key == key
                )
            )
            if existing is not None:
                if existing.request_hash != body_hash:
                    raise ProblemError(422, "Idempotency key reused",
                                       "This key was used with a different request body")
                return _raw_response(               ### replay: nafs el status w el body bezabt
                    existing.status_code, existing.response_body,
                    "application/json" if existing.status_code < 400 else "application/problem+json",
                    replayed=True,
                )

            source = s.get(Account, payload.from_account_id)
            if source is None or source.owner_id != customer:
                raise ProblemError(404, "Account not found")  ### 404 mesh 403, mafeesh tasreeb
            if s.get(Account, payload.to_account_id) is None:
                raise ProblemError(422, "Validation error", "Unknown destination account")

            amount = payload.amount_piastres
            debit = s.execute(
                update(Account)
                .where(Account.id == source.id, Account.balance_piastres >= amount)
                .values(balance_piastres=Account.balance_piastres - amount)
            )
            if debit.rowcount == 0:
                        ### 409 bardo bensagelha 3ashan teet3ad nafs el rad
                status = 409
                result = problem_body(409, "Insufficient funds", "Balance is too low for this transfer")
            else:
                s.execute(
                    update(Account)
                    .where(Account.id == payload.to_account_id)
                    .values(balance_piastres=Account.balance_piastres + amount)
                )
                transfer = Transfer(
                    id="trf_" + uuid.uuid4().hex,
                    from_account_id=payload.from_account_id,
                    to_account_id=payload.to_account_id,
                    amount_piastres=amount,
                    memo=payload.memo,
                    status="completed",
                )
                s.add(transfer)
                status = 201
                result = _transfer_json(transfer)

            text = json.dumps(result)
            s.add(IdempotencyRecord(customer_id=customer, key=key, request_hash=body_hash,
                                    status_code=status, response_body=text))
            media = "application/json" if status < 400 else "application/problem+json"
            return _raw_response(status, text, media)

   
    @app.get("/v1/accounts/{account_id}")
    def get_account(account_id: str, customer: str = Depends(current_customer)):
        with session_factory() as s:
            acc = s.get(Account, account_id)
            if acc is None or acc.owner_id != customer:
                raise ProblemError(404, "Account not found")
            return {"id": acc.id, "balance_piastres": acc.balance_piastres, "currency": acc.currency}

    
    @app.get("/v1/transfers/{transfer_id}")
    def get_transfer(transfer_id: str, customer: str = Depends(current_customer)):
        with session_factory() as s:
            t = s.get(Transfer, transfer_id)
            if t is None:
                raise ProblemError(404, "Transfer not found")
                   ### el sender aw el receiver bas el yeshoof
            owners = {
                a.owner_id
                for a in (s.get(Account, t.from_account_id), s.get(Account, t.to_account_id))
                if a is not None
            }
            if customer not in owners:
                raise ProblemError(404, "Transfer not found")
            return _transfer_json(t)

    return app


def _errors(exc) -> list[dict]:
### bnesheel el input w el ctx 3ashan el JSON yekoon serializable
    return exc.errors(include_url=False, include_context=False, include_input=False)