import pytest
from hypothesis import HealthCheck, given, settings as hsettings, strategies as st
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.main import create_app
from app.models import Account, Base, IdempotencyRecord, Transfer
from app.settings import Settings
from fastapi.testclient import TestClient


### H03: el database nafsaha betrfod el rows el ghalat
def test_db_refuses_zero_amount(client):
    with Session(client.app.state.engine) as s:
        s.add(Transfer(id="trf_bad", from_account_id="acc_dina", to_account_id="acc_karim",
                       amount_piastres=0, status="completed"))
        with pytest.raises(IntegrityError):
            s.commit()


def test_db_refuses_duplicate_customer_key(client):
    with Session(client.app.state.engine) as s:
        s.add(IdempotencyRecord(customer_id="c", key="k", request_hash="h", status_code=201, response_body="{}"))
        s.commit()
        s.add(IdempotencyRecord(customer_id="c", key="k", request_hash="h2", status_code=201, response_body="{}"))
        with pytest.raises(IntegrityError):
            s.commit()


### H08: random transfers bein 4 accounts, w mawdoo3 model ledger yetaabe2 el app
IDS = ["a1", "a2", "a3", "a4"]
OWNERS = {"a1": "c1", "a2": "c2", "a3": "c3", "a4": "c4"}
TOKENS = {f"t{i}": f"c{i}" for i in range(1, 5)}


def fresh_client():
    ### clock sabet w capacity kebeera 3ashan el rate limit mayetda5alsh
    s = Settings(database_url="sqlite+pysqlite:///:memory:", api_tokens=TOKENS,
                 rate_limit_capacity=10_000, clock=lambda: 1000.0)
    app = create_app(s)
    Base.metadata.create_all(app.state.engine)
    with Session(app.state.engine) as db:
        db.add_all([Account(id=a, owner_id=OWNERS[a], balance_piastres=1000) for a in IDS])
        db.commit()
    return TestClient(app)


op = st.tuples(st.sampled_from(IDS), st.sampled_from(IDS), st.integers(min_value=1, max_value=1500))


@hsettings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(ops=st.lists(op, min_size=1, max_size=25))
def test_money_is_conserved(ops):
    client = fresh_client()
    ledger = {a: 1000 for a in IDS}  ### el model beta3na
    for n, (src, dst, amt) in enumerate(ops):
        tok = "t" + src[1]
        r = client.post("/v1/transfers",
                        json={"from_account_id": src, "to_account_id": dst, "amount_piastres": amt},
                        headers={"Authorization": f"Bearer {tok}", "Idempotency-Key": f"k{n}"})
        if src == dst:
            assert r.status_code == 422
        elif ledger[src] >= amt:
            assert r.status_code == 201
            ledger[src] -= amt
            ledger[dst] += amt
        else:
            assert r.status_code == 409
        ### net2aked men kol balance b3d kol 3amaleya
        for a in IDS:
            got = client.get(f"/v1/accounts/{a}", headers={"Authorization": f"Bearer t{a[1]}"}).json()
            assert got["balance_piastres"] == ledger[a] >= 0
        assert sum(ledger.values()) == 4000