"""Paging through GET /calibrations with limit and offset."""


def ids_of(client, **params):
    response = client.get("/calibrations", params=params)
    assert response.status_code == 200, response.text
    return [item["id"] for item in response.json()]


def test_pages_are_newest_first_and_cover_everything_once(client, create_cal, fake_clock):
    for _ in range(7):
        create_cal()
        fake_clock.advance(minutes=1)
    assert ids_of(client, limit=3, offset=0) == [7, 6, 5]
    assert ids_of(client, limit=3, offset=3) == [4, 3, 2]
    assert ids_of(client, limit=3, offset=6) == [1]
    assert ids_of(client, limit=3, offset=9) == []


def test_same_timestamp_rows_still_page_in_a_stable_order(client, create_cal):
    # The fake clock never moves here, so all five share one created_at and the
    # id tie-breaker is the only thing keeping the order fixed.
    for _ in range(5):
        create_cal()
    assert ids_of(client, limit=2, offset=0) == [5, 4]
    assert ids_of(client, limit=2, offset=2) == [3, 2]
    assert ids_of(client, limit=2, offset=4) == [1]


def test_paging_works_together_with_filters(client, create_cal, fake_clock):
    for name in ("alice", "bob", "alice", "alice"):
        create_cal(username=name)
        fake_clock.advance(minutes=1)
    assert ids_of(client, username="alice", limit=2, offset=0) == [4, 3]
    assert ids_of(client, username="alice", limit=2, offset=2) == [1]


def test_limit_and_offset_bounds(client):
    for params in ({"limit": 0}, {"limit": 201}, {"offset": -1}):
        assert client.get("/calibrations", params=params).status_code == 422, params
