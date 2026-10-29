"""Use case 1: creating and fetching calibrations.

Covers the happy path (server assigns id and created_at) and the ways input
can be wrong: missing fields, wrong types, NaN, blank strings
and unknown fields.
"""
from tests.conftest import T0


def test_create_returns_server_assigned_id_and_timestamp(client):
    response = client.post(
        "/calibrations",
        json={"calibration_type": "gain", "value": 1.5, "username": "bob"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["id"] == 1
    assert body["calibration_type"] == "gain"
    assert body["value"] == 1.5
    assert body["username"] == "bob"
    assert body["created_at"].startswith("2026-01-01T12:00:00")  # from the fake clock


def test_client_cannot_choose_timestamp(client):
    # Rejected loudly rather than ignored, so a client never believes it set one.
    response = client.post(
        "/calibrations",
        json={
            "calibration_type": "gain",
            "value": 1.5,
            "username": "bob",
            "created_at": "1999-01-01T00:00:00Z",
        },
    )
    assert response.status_code == 422
    assert client.get("/calibrations").json() == []  # nothing was created


def test_value_must_be_a_real_number(client):
    for bad in (True, False, "1.5", None, [1.0]):
        response = client.post(
            "/calibrations", json={"calibration_type": "gain", "value": bad, "username": "a"}
        )
        assert response.status_code == 422, bad






def test_whitespace_is_stripped(client):
    response = client.post(
        "/calibrations",
        json={"calibration_type": "  gain ", "value": 2, "username": " bob  "},
    )
    assert response.json()["calibration_type"] == "gain"
    assert response.json()["username"] == "bob"


def test_negative_and_integer_values_are_accepted(client):
    assert client.post(
        "/calibrations", json={"calibration_type": "temperature", "value": -0.3, "username": "c"}
    ).status_code == 201
    assert client.post(
        "/calibrations", json={"calibration_type": "pressure", "value": 101, "username": "c"}
    ).status_code == 201


def test_validation_errors(client):
    bad_bodies = [
        {"value": 1.0, "username": "a"},  # missing type
        {"calibration_type": "gain", "username": "a"},  # missing value
        {"calibration_type": "gain", "value": 1.0},  # missing username
        {"calibration_type": "gain", "value": "abc", "username": "a"},  # non-numeric value
        {"calibration_type": "", "value": 1.0, "username": "a"},  # empty type
        {"calibration_type": "gain", "value": 1.0, "username": "   "},  # blank username
        {"calibration_type": "x" * 65, "value": 1.0, "username": "a"},  # too long
    ]
    for body in bad_bodies:
        assert client.post("/calibrations", json=body).status_code == 422, body


def test_nan_and_infinity_rejected(client):
    # Python's json allows these tokens; Starlette's parser does too, so send raw text.
    for literal in ("NaN", "Infinity", "-Infinity"):
        response = client.post(
            "/calibrations",
            content=f'{{"calibration_type": "gain", "value": {literal}, "username": "a"}}',
            headers={"content-type": "application/json"},
        )
        assert response.status_code == 422, literal


def test_get_by_id(client, create_cal):
    created = create_cal()
    assert client.get(f"/calibrations/{created['id']}").json() == created


def test_get_unknown_id_is_404(client):
    assert client.get("/calibrations/999").status_code == 404


def test_timestamps_follow_the_clock(client, create_cal, fake_clock):
    first = create_cal()
    fake_clock.advance(minutes=5)
    second = create_cal()
    assert first["created_at"] < second["created_at"]
    assert second["created_at"].startswith("2026-01-01T12:05:00")
    assert T0.isoformat().startswith("2026-01-01T12:00:00")


def test_root_redirects_to_the_api_docs(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code in (302, 307)
    assert response.headers["location"] == "/docs"
    assert client.get("/", follow_redirects=True).status_code == 200  # the docs page loads
