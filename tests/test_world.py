"""World module tests: landmarks, distance, hearing range, location detection."""
import math


def test_landmarks_seeded(tmp_db):
    from engine import world
    lms = world.list_landmarks()
    assert len(lms) == 14
    ids = {l["id"] for l in lms}
    assert "town_hall" in ids
    assert "library" in ids
    assert "plaza" in ids
    # Grid coords are in bounds
    for l in lms:
        assert 0 <= l["x"] < world.GRID_W
        assert 0 <= l["y"] < world.GRID_H


def test_distance_function():
    from engine import world
    assert world.distance((0, 0), (3, 4)) == 5.0
    assert world.distance((10, 10), (10, 10)) == 0
    assert world.distance((0, 0), (0, 0)) == 0


def test_landmark_at(tmp_db):
    from engine import world
    # Town Hall is at (120, 120)
    assert world.landmark_at(120, 120) is not None
    assert world.landmark_at(120, 120)["id"] == "town_hall"
    # far away -> None
    assert world.landmark_at(0, 0) is None
    # within 4 units of cafe (100, 100)
    assert world.landmark_at(101, 100) is not None
    assert world.landmark_at(101, 100)["id"] == "cafe"


def test_hearing_distance():
    from engine import world
    assert world.HEARING_DISTANCE == 25.0


def test_nearby_agents(tmp_db):
    from engine import agents as agents_mod
    from engine import world
    # Move spark to town_hall (120, 120), anchor stays at home_anchor (30, 30)
    spark = agents_mod.get("spark")
    agents_mod.update_position("spark", 120, 120)
    # From anchor's perspective at (30, 30), spark at (120, 120) is far
    near = world.nearby_agents("anchor", 30, 30, radius=25.0)
    assert all(n["id"] != "spark" for n in near)
    # With a large radius, spark is in
    near2 = world.nearby_agents("anchor", 30, 30, radius=200.0)
    ids = {n["id"] for n in near2}
    assert "spark" in ids
    # Excludes self
    assert all(n["id"] != "anchor" for n in near2)


def test_get_landmark(tmp_db):
    from engine import world
    lm = world.get_landmark("town_hall")
    assert lm is not None
    assert lm["name"] == "Town Hall"
    assert world.get_landmark("does_not_exist") is None
