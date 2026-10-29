"""Use cases 2, 3 and 5: adding to a tag, removing from a tag, and reading a
calibration's tags (now, at a past time, or with full history).

Also covers repeating requests (PUT and DELETE are idempotent), re-adding a tag
after removal.
"""
from datetime import timedelta

from tests.conftest import T0


def tags_of(client, calibration_id, **params):
    response = client.get(f"/calibrations/{calibration_id}/tags", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def tag_names(memberships):
    return [m["tag"] for m in memberships]


# ---- adding ---------------------------------------------------------------
def test_add_creates_membership(client, create_cal):
    cal = create_cal()
    response = client.put(f"/calibrations/{cal['id']}/tags/golden")
    assert response.status_code == 201
    body = response.json()
    assert body["calibration_id"] == cal["id"]
    assert body["tag"] == "golden"
    assert body["removed_at"] is None


def test_add_is_idempotent(client, create_cal, fake_clock):
    cal = create_cal()
    first = client.put(f"/calibrations/{cal['id']}/tags/golden")
    fake_clock.advance(minutes=10)
    second = client.put(f"/calibrations/{cal['id']}/tags/golden")

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json() == first.json()  # original added_at is kept
    assert len(tags_of(client, cal["id"], include_history=True)) == 1


def test_add_to_unknown_calibration_is_404(client):
    assert client.put("/calibrations/999/tags/golden").status_code == 404


def test_blank_tag_is_rejected(client, create_cal):
    cal = create_cal()
    assert client.put(f"/calibrations/{cal['id']}/tags/%20%20").status_code == 422




def test_tag_of_exactly_max_length_is_accepted_and_one_more_is_not(client, create_cal):
    cal = create_cal()
    assert client.put(f"/calibrations/{cal['id']}/tags/{'x' * 255}").status_code == 201
    assert client.put(f"/calibrations/{cal['id']}/tags/{'x' * 256}").status_code == 422


def test_non_ascii_tags_round_trip(client, create_cal):
    cal = create_cal()
    client.put(f"/calibrations/{cal['id']}/tags/caf%C3%A9")
    assert tag_names(tags_of(client, cal["id"])) == ["café"]


def test_tag_whitespace_is_trimmed_and_case_is_preserved(client, create_cal):
    cal = create_cal()
    client.put(f"/calibrations/{cal['id']}/tags/%20Golden%20")
    client.put(f"/calibrations/{cal['id']}/tags/golden")
    assert tag_names(tags_of(client, cal["id"])) == ["Golden", "golden"]


def test_tag_can_contain_slashes_and_spaces(client, create_cal):
    cal = create_cal()
    client.put(f"/calibrations/{cal['id']}/tags/fab/lot%207")
    assert tag_names(tags_of(client, cal["id"])) == ["fab/lot 7"]
    assert client.delete(f"/calibrations/{cal['id']}/tags/fab/lot%207").status_code == 204
    assert tags_of(client, cal["id"]) == []


def test_calibration_can_be_in_many_tags_and_tag_can_hold_many_calibrations(client, create_cal):
    a, b = create_cal(), create_cal(username="bob")
    for tag in ("one", "two"):
        client.put(f"/calibrations/{a['id']}/tags/{tag}")
    client.put(f"/calibrations/{b['id']}/tags/one")

    assert tag_names(tags_of(client, a["id"])) == ["one", "two"]
    assert tag_names(tags_of(client, b["id"])) == ["one"]
    in_one = client.get("/calibrations", params={"tag": "one"}).json()
    assert {c["id"] for c in in_one} == {a["id"], b["id"]}


# ---- removing -------------------------------------------------------------
def test_remove_closes_membership_but_keeps_history(client, create_cal, fake_clock):
    cal = create_cal()
    client.put(f"/calibrations/{cal['id']}/tags/golden")
    fake_clock.advance(hours=1)
    assert client.delete(f"/calibrations/{cal['id']}/tags/golden").status_code == 204

    assert tags_of(client, cal["id"]) == []
    history = tags_of(client, cal["id"], include_history=True)
    assert len(history) == 1
    assert history[0]["removed_at"].startswith("2026-01-01T13:00:00")


def test_remove_when_not_in_tag_is_a_noop(client, create_cal):
    cal = create_cal()
    assert client.delete(f"/calibrations/{cal['id']}/tags/never-added").status_code == 204
    assert tags_of(client, cal["id"], include_history=True) == []


def test_remove_twice_is_idempotent(client, create_cal, fake_clock):
    cal = create_cal()
    client.put(f"/calibrations/{cal['id']}/tags/golden")
    fake_clock.advance(minutes=1)
    client.delete(f"/calibrations/{cal['id']}/tags/golden")
    fake_clock.advance(minutes=1)
    assert client.delete(f"/calibrations/{cal['id']}/tags/golden").status_code == 204

    history = tags_of(client, cal["id"], include_history=True)
    assert len(history) == 1
    assert history[0]["removed_at"].startswith("2026-01-01T12:01:00")  # first removal wins


def test_remove_from_unknown_calibration_is_404(client):
    assert client.delete("/calibrations/999/tags/golden").status_code == 404


def test_readd_after_removal_opens_a_new_stay(client, create_cal, fake_clock):
    cal = create_cal()
    client.put(f"/calibrations/{cal['id']}/tags/golden")
    fake_clock.advance(hours=1)
    client.delete(f"/calibrations/{cal['id']}/tags/golden")
    fake_clock.advance(hours=1)
    again = client.put(f"/calibrations/{cal['id']}/tags/golden")

    assert again.status_code == 201  # a genuinely new membership
    history = tags_of(client, cal["id"], include_history=True)
    assert len(history) == 2
    assert history[0]["removed_at"] is not None
    assert history[1]["removed_at"] is None


# ---- time travel ----------------------------------------------------------
def test_tags_as_of_across_add_remove_readd(client, create_cal, fake_clock):
    cal = create_cal()  # created T0
    fake_clock.advance(hours=1)
    client.put(f"/calibrations/{cal['id']}/tags/golden")  # in at T0+1h
    fake_clock.advance(hours=1)
    client.delete(f"/calibrations/{cal['id']}/tags/golden")  # out at T0+2h
    fake_clock.advance(hours=1)
    client.put(f"/calibrations/{cal['id']}/tags/golden")  # back in at T0+3h

    def in_tag_at(delta):
        return tag_names(tags_of(client, cal["id"], as_of=(T0 + delta).isoformat())) == ["golden"]

    assert not in_tag_at(timedelta(minutes=30))  # before first add
    assert in_tag_at(timedelta(hours=1))  # exactly when added: inclusive
    assert in_tag_at(timedelta(minutes=90))  # during first stay
    assert not in_tag_at(timedelta(hours=2))  # exactly when removed: exclusive
    assert not in_tag_at(timedelta(minutes=150))  # between stays
    assert in_tag_at(timedelta(hours=3))  # second stay starts
    assert in_tag_at(timedelta(days=30))  # far future = current state
    assert tag_names(tags_of(client, cal["id"])) == ["golden"]  # no as_of = now


def test_as_of_and_include_history_cannot_be_combined(client, create_cal):
    cal = create_cal()
    response = client.get(
        f"/calibrations/{cal['id']}/tags",
        params={"as_of": T0.isoformat(), "include_history": "true"},
    )
    assert response.status_code == 422


def test_tags_of_unknown_calibration_is_404(client):
    assert client.get("/calibrations/999/tags").status_code == 404
