"""Use case 4: searching calibrations by user, time, type and tag.

Each filter is tested alone and combined with others. The time-range tests
check the boundaries (created_after is inclusive, created_before is exclusive),
and the tag tests check both "in the tag now" and "was in the tag at time T".
"""
from datetime import timedelta

import pytest

from tests.conftest import T0


@pytest.fixture
def populated(create_cal, fake_clock):
    """Five calibrations, one per minute, starting at T0."""
    specs = [
        ("alice", "offset", 1.0),  # T0
        ("bob", "gain", 1.5),  # T0+1m
        ("alice", "gain", 1.6),  # T0+2m
        ("carol", "offset", 0.9),  # T0+3m
        ("alice", "offset", 1.1),  # T0+4m
    ]
    created = []
    for username, calibration_type, value in specs:
        created.append(create_cal(username, calibration_type, value))
        fake_clock.advance(minutes=1)
    return created


def search(client, **params):
    response = client.get("/calibrations", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def ids(items):
    return {item["id"] for item in items}


def test_no_filters_returns_everything_newest_first(client, populated):
    items = search(client)
    assert [i["id"] for i in items] == [5, 4, 3, 2, 1]


def test_filter_by_username(client, populated):
    assert ids(search(client, username="alice")) == {1, 3, 5}
    assert search(client, username="nobody") == []


def test_filter_by_type(client, populated):
    assert ids(search(client, calibration_type="gain")) == {2, 3}


def test_filters_combine_with_and(client, populated):
    assert ids(search(client, username="alice", calibration_type="offset")) == {1, 5}


def test_time_range_is_inclusive_start_exclusive_end(client, populated):
    start, end = T0 + timedelta(minutes=1), T0 + timedelta(minutes=3)
    items = search(client, created_after=start.isoformat(), created_before=end.isoformat())
    assert ids(items) == {2, 3}  # T0+1m included, T0+3m excluded


def test_open_ended_time_ranges(client, populated):
    cutoff = (T0 + timedelta(minutes=3)).isoformat()
    assert ids(search(client, created_after=cutoff)) == {4, 5}
    assert ids(search(client, created_before=cutoff)) == {1, 2, 3}


def test_time_filter_respects_offsets_and_naive_means_utc(client, populated):
    # 17:00+05:00 is 12:00 UTC == T0
    assert ids(search(client, created_before="2026-01-01T17:00:00+05:00")) == set()
    assert ids(search(client, created_after="2026-01-01T17:00:00+05:00")) == {1, 2, 3, 4, 5}
    # naive timestamp is treated as UTC
    assert ids(search(client, created_after="2026-01-01T12:03:00")) == {4, 5}


def test_inverted_time_range_is_rejected(client, populated):
    response = client.get(
        "/calibrations",
        params={"created_after": (T0 + timedelta(hours=1)).isoformat(), "created_before": T0.isoformat()},
    )
    assert response.status_code == 422


def test_unparseable_time_is_rejected(client, populated):
    assert client.get("/calibrations", params={"created_after": "yesterday"}).status_code == 422




def test_date_only_time_means_midnight_utc(client, populated):
    assert ids(search(client, created_after="2026-01-01")) == {1, 2, 3, 4, 5}
    assert search(client, created_after="2026-01-02") == []


def test_empty_tag_filter_is_rejected(client, populated):
    assert client.get("/calibrations", params={"tag": ""}).status_code == 422


def test_filter_by_current_tag(client, populated, fake_clock):
    client.put("/calibrations/1/tags/golden")
    client.put("/calibrations/3/tags/golden")
    client.delete("/calibrations/3/tags/golden")
    assert ids(search(client, tag="golden")) == {1}
    assert search(client, tag="other") == []


def test_filter_by_tag_as_of(client, create_cal, fake_clock):
    a, b = create_cal(), create_cal(username="bob")
    fake_clock.advance(hours=1)
    client.put(f"/calibrations/{a['id']}/tags/golden")  # a in at +1h
    fake_clock.advance(hours=1)
    client.put(f"/calibrations/{b['id']}/tags/golden")  # b in at +2h
    client.delete(f"/calibrations/{a['id']}/tags/golden")  # a out at +2h (swap)

    def members_at(delta):
        return ids(search(client, tag="golden", tag_as_of=(T0 + delta).isoformat()))

    assert members_at(timedelta(minutes=30)) == set()
    assert members_at(timedelta(minutes=90)) == {a["id"]}
    assert members_at(timedelta(hours=2)) == {b["id"]}  # the swap instant
    assert ids(search(client, tag="golden")) == {b["id"]}  # now


def test_tag_as_of_without_tag_is_rejected(client, populated):
    response = client.get("/calibrations", params={"tag_as_of": T0.isoformat()})
    assert response.status_code == 422


def test_calibration_with_multiple_stays_appears_once(client, create_cal, fake_clock):
    cal = create_cal()
    for _ in range(3):
        fake_clock.advance(minutes=1)
        client.put(f"/calibrations/{cal['id']}/tags/golden")
        fake_clock.advance(minutes=1)
        client.delete(f"/calibrations/{cal['id']}/tags/golden")
    fake_clock.advance(minutes=1)
    client.put(f"/calibrations/{cal['id']}/tags/golden")
    assert [c["id"] for c in search(client, tag="golden")] == [cal["id"]]


def test_all_filters_together(client, populated):
    client.put("/calibrations/1/tags/golden")
    client.put("/calibrations/2/tags/golden")
    client.put("/calibrations/5/tags/golden")
    items = search(
        client,
        username="alice",
        calibration_type="offset",
        tag="golden",
        created_after=T0.isoformat(),
        created_before=(T0 + timedelta(minutes=10)).isoformat(),
    )
    assert ids(items) == {1, 5}








def search_raw(client, query_string):
    response = client.get(f"/calibrations?{query_string}")
    assert response.status_code == 200, response.text
    return response.json()
