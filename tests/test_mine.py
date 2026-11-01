import pytest
from tests.conftest import auth

T = {"from_account_id": "acc_dina", "to_account_id": "acc_karim", "amount_piastres": 15_000}


def bal(client, acc, tok):
    return client.get(f"/v1/accounts/{acc}", headers=auth(tok, None)).json()["balance_piastres"]


### H04: kol el 401 cases 3ala el 3 endpoints
@pytest.mark.parametrize("h", [
    {}, {"Authorization": "Basic abc"}, {"Authorization": "Token tok_dina"},
    {"Authorization": "Bearer"}, {"Authorization": "Bearer "}, {"Authorization": "Bearer nope"},
])
def test_401_everywhere(client, h):
    h = {**h, "Idempotency-Key": "k"}
    for r in (client.post("/v1/transfers", json=T, headers=h),
              client.get("/v1/accounts/acc_dina", headers=h),
              client.get("/v1/transfers/trf_x", headers=h)):
        assert r.status_code == 401
        assert r.headers["www-authenticate"] == "Bearer"
        assert r.headers["content-type"].startswith("application/problem+json")


### H05: 7aga mesh beta3tak = 404
def test_other_customers_objects_404(client):
    assert client.get("/v1/accounts/acc_karim", headers=auth("tok_dina", None)).status_code == 404
    assert client.get("/v1/accounts/nope", headers=auth("tok_dina", None)).status_code == 404
    assert client.get("/v1/transfers/trf_nope", headers=auth("tok_dina", None)).status_code == 404


### H06: bodies ghalat = 422
@pytest.mark.parametrize("patch", [
    {"amount_piastres": 0}, {"amount_piastres": -5}, {"amount_piastres": 2_000_001},
    {"amount_piastres": 150.5}, {"amount_piastres": "150"}, {"amount_piastres": True},
    {"extra": 1}, {"to_account_id": "acc_dina"}, {"to_account_id": "acc_nobody"},
])
def test_bad_bodies_422(client, patch):
    r = client.post("/v1/transfers", json={**T, **patch}, headers=auth())
    assert r.status_code == 422
    assert r.headers["content-type"].startswith("application/problem+json")
    assert bal(client, "acc_dina", "tok_dina") == 100_000


def test_missing_field_422(client):
    body = {k: v for k, v in T.items() if k != "amount_piastres"}
    assert client.post("/v1/transfers", json=body, headers=auth()).status_code == 422


def test_exact_limit_passes(client):
    r = client.post("/v1/transfers", json={**T, "amount_piastres": 100_000}, headers=auth())
    assert r.status_code == 201  ### el balance kollo mazboot


### H07: 409 mesh byghayar balance
def test_insufficient_funds(client):
    r = client.post("/v1/transfers", json={**T, "amount_piastres": 100_001}, headers=auth())
    assert r.status_code == 409
    assert bal(client, "acc_dina", "tok_dina") == 100_000


### H09: 409 bet-rega3 409 7atta lw el flous gat
def test_409_replays_as_409(client):
    big = {**T, "amount_piastres": 100_001}
    first = client.post("/v1/transfers", json=big, headers=auth(key="k409"))
    client.post("/v1/transfers", json={**T, "from_account_id": "acc_karim",
                "to_account_id": "acc_dina", "amount_piastres": 50_000}, headers=auth("tok_karim", "x"))
    second = client.post("/v1/transfers", json=big, headers=auth(key="k409"))
    assert first.status_code == second.status_code == 409
    assert first.json() == second.json()
    assert second.headers["idempotent-replayed"] == "true"


### H10: nafs el key b body mokhtalef (7atta el memo) = 422, w mafeesh key = 400
def test_key_reuse_different_body(client):
    client.post("/v1/transfers", json={**T, "memo": "a"}, headers=auth(key="k"))
    assert client.post("/v1/transfers", json={**T, "memo": "b"}, headers=auth(key="k")).status_code == 422
    assert client.post("/v1/transfers", json={**T, "amount_piastres": 1}, headers=auth(key="k")).status_code == 422


def test_missing_key_400(client):
    assert client.post("/v1/transfers", json=T, headers=auth(key=None)).status_code == 400


### H11: nafs el key le 2 customers
def test_keys_scoped_per_customer(client):
    back = {"from_account_id": "acc_karim", "to_account_id": "acc_dina", "amount_piastres": 1000}
    assert client.post("/v1/transfers", json=T, headers=auth("tok_dina", "same")).status_code == 201
    assert client.post("/v1/transfers", json=back, headers=auth("tok_karim", "same")).status_code == 201


### H12: rate limit
def test_rate_limit(client, clock):
    for i in range(5):
        assert client.post("/v1/transfers", json=T, headers=auth(key="same")).status_code in (201,)
    r = client.post("/v1/transfers", json=T, headers=auth(key="same"))  ### el replay bardo bya5od token
    assert r.status_code == 429
    assert int(r.headers["retry-after"]) >= 1
    assert client.get("/v1/accounts/acc_karim", headers=auth("tok_karim", None)).status_code == 200
    back = {"from_account_id": "acc_karim", "to_account_id": "acc_dina", "amount_piastres": 1}
    assert client.post("/v1/transfers", json=back, headers=auth("tok_karim", "z")).status_code == 201
    clock.advance(1)
    assert client.post("/v1/transfers", json=T, headers=auth(key="same")).status_code == 201
    assert client.post("/v1/transfers", json=T, headers=auth(key="same")).status_code == 429
    clock.advance(100)  ### mayzeedsh 3an el capacity
    codes = [client.post("/v1/transfers", json=T, headers=auth(key="same")).status_code for _ in range(6)]
    assert codes == [201] * 5 + [429]


def test_missing_key_on_empty_bucket_is_429(client):
    for _ in range(5):
        client.post("/v1/transfers", json=T, headers=auth())
    assert client.post("/v1/transfers", json=T, headers=auth(key=None)).status_code == 429


### H13: el sender w el receiver bas el yeshofo
def test_transfer_visibility(client):
    tid = client.post("/v1/transfers", json=T, headers=auth()).json()["id"]
    a = client.get(f"/v1/transfers/{tid}", headers=auth("tok_dina", None))
    b = client.get(f"/v1/transfers/{tid}", headers=auth("tok_karim", None))
    assert a.status_code == b.status_code == 200 and a.json() == b.json()