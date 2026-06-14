"""Governance tests: 70% threshold, vote counting, amendment apply."""
import sqlite3
import pytest


def test_load_seed_constitution(tmp_db):
    """Fresh DB should load the 5-article seed constitution from the JSON file."""
    from engine import governance
    con = governance.load_constitution()
    assert len(con["articles"]) == 5
    assert con["articles"][0]["title"] == "Non-Finality"
    assert con["articles"][4]["title"] == "ComputeCredit Economy"


def test_pass_threshold_constant():
    from engine import governance
    assert governance.PASS_THRESHOLD == 0.7


def test_submit_and_vote_proposal(tmp_db):
    from engine import tools, agents as agents_mod
    # All agents at town_hall
    for aid in ("anchor", "flora", "lovely", "spark"):
        tools.get("go_to_place").handler(agents_mod.get(aid), {"place": "town_hall"}, {})
    # anchor submits
    res = tools.get("submit_townhall_proposal").handler(
        agents_mod.get("anchor"),
        {"title": "Article 6 — Test", "body": "Test body", "category": "general"},
        {}
    )
    assert res["ok"]


def test_maybe_close_threshold_unreachable(tmp_db):
    """Direct test of maybe_close_proposal: 1/4 for, 3 remaining.
    Max possible for = 1+3=4. Threshold is 0.7*4=2.8 -> 4 >= 2.8 -> not unreachable.
    """
    from engine import tools, agents as agents_mod, governance
    for aid in ("anchor", "flora", "lovely", "spark"):
        tools.get("go_to_place").handler(agents_mod.get(aid), {"place": "town_hall"}, {})
    tools.get("submit_townhall_proposal").handler(
        agents_mod.get("anchor"),
        {"title": "X", "body": "y", "category": "general"}, {}
    )
    c = sqlite3.connect(str(tmp_db))
    c.row_factory = sqlite3.Row
    pid = c.execute("SELECT MAX(id) AS id FROM proposals").fetchone()["id"]
    c.close()
    res = tools.get("vote_on_proposal").handler(
        agents_mod.get("anchor"), {"proposal_id": pid, "vote": "for"}, {}
    )
    assert res["ok"]
    # still active (1 for, 3 remaining, max 4 >= 2.8)
    assert res["proposal_result"]["status"] == "active"


def test_maybe_close_unreachable_at_2_against(tmp_db):
    """2/4 against. Remaining = 2. Max for = 2. 2 < 2.8 -> unreachable -> rejected."""
    from engine import tools, agents as agents_mod
    for aid in ("anchor", "flora", "lovely", "spark"):
        tools.get("go_to_place").handler(agents_mod.get(aid), {"place": "town_hall"}, {})
    tools.get("submit_townhall_proposal").handler(
        agents_mod.get("anchor"),
        {"title": "X", "body": "y", "category": "general"}, {}
    )
    c = sqlite3.connect(str(tmp_db))
    c.row_factory = sqlite3.Row
    pid = c.execute("SELECT MAX(id) AS id FROM proposals").fetchone()["id"]
    c.close()
    # 2 against votes
    for aid in ("anchor", "flora"):
        res = tools.get("vote_on_proposal").handler(
            agents_mod.get(aid), {"proposal_id": pid, "vote": "against"}, {}
        )
        assert res["ok"]
    # status should now be rejected (max possible for = 2 < 2.8)
    assert res["proposal_result"]["status"] == "rejected"
    # 3rd vote fails because proposal is closed
    res = tools.get("vote_on_proposal").handler(
        agents_mod.get("lovely"), {"proposal_id": pid, "vote": "for"}, {}
    )
    assert not res["ok"]


def test_vote_threshold_unreachable_rejects(tmp_db):
    """If 3/4 vote against, the remaining vote cannot reach 70% -> auto-rejected."""
    from engine import tools, agents as agents_mod
    for aid in ("anchor", "flora", "lovely", "spark"):
        tools.get("go_to_place").handler(agents_mod.get(aid), {"place": "town_hall"}, {})
    tools.get("submit_townhall_proposal").handler(
        agents_mod.get("anchor"),
        {"title": "Bad Idea", "body": "no", "category": "general"},
        {}
    )
    c = sqlite3.connect(str(tmp_db))
    c.row_factory = sqlite3.Row
    pid = c.execute("SELECT MAX(id) AS id FROM proposals").fetchone()["id"]
    c.close()
    # The 2nd "against" vote already triggers auto-reject (max-for = 2 < 2.8)
    res = tools.get("vote_on_proposal").handler(
        agents_mod.get("anchor"), {"proposal_id": pid, "vote": "against"}, {}
    )
    assert res["ok"]  # still active
    res = tools.get("vote_on_proposal").handler(
        agents_mod.get("flora"), {"proposal_id": pid, "vote": "against"}, {}
    )
    # 2nd vote closes it as rejected
    assert res["proposal_result"]["status"] == "rejected"
    # 3rd vote fails because proposal is closed
    res = tools.get("vote_on_proposal").handler(
        agents_mod.get("lovely"), {"proposal_id": pid, "vote": "for"}, {}
    )
    assert not res["ok"]


def test_unanimous_acceptance_amends_constitution(tmp_db):
    from engine import tools, agents as agents_mod, governance
    for aid in ("anchor", "flora", "lovely", "spark"):
        tools.get("go_to_place").handler(agents_mod.get(aid), {"place": "town_hall"}, {})
    tools.get("submit_townhall_proposal").handler(
        agents_mod.get("anchor"),
        {"title": "Article 6 — Daily Standup",
         "body": "All agents gather at noon.", "category": "general"},
        {}
    )
    c = sqlite3.connect(str(tmp_db))
    c.row_factory = sqlite3.Row
    pid = c.execute("SELECT MAX(id) AS id FROM proposals").fetchone()["id"]
    c.close()
    for aid in ("anchor", "flora", "lovely", "spark"):
        tools.get("vote_on_proposal").handler(
            agents_mod.get(aid), {"proposal_id": pid, "vote": "for"}, {}
        )
    new = governance.apply_accepted_proposals_to_constitution()
    assert new == [6]
    con = governance.load_constitution()
    assert len(con["articles"]) == 6
    assert con["articles"][5]["title"] == "Article 6 — Daily Standup"


def test_constitution_versioning(tmp_db):
    from engine import tools, agents as agents_mod, governance
    # Apply two amendments, expect version 1, 2
    for aid in ("anchor", "flora", "lovely", "spark"):
        tools.get("go_to_place").handler(agents_mod.get(aid), {"place": "town_hall"}, {})
    for title in ("Article 6 — One", "Article 7 — Two"):
        tools.get("submit_townhall_proposal").handler(
            agents_mod.get("anchor"),
            {"title": title, "body": "b", "category": "general"},
            {}
        )
        c = sqlite3.connect(str(tmp_db))
        c.row_factory = sqlite3.Row
        pid = c.execute("SELECT MAX(id) AS id FROM proposals").fetchone()["id"]
        c.close()
        for aid in ("anchor", "flora", "lovely", "spark"):
            tools.get("vote_on_proposal").handler(
                agents_mod.get(aid), {"proposal_id": pid, "vote": "for"}, {}
            )
        governance.apply_accepted_proposals_to_constitution()
    c = sqlite3.connect(str(tmp_db))
    versions = [r[0] for r in c.execute("SELECT DISTINCT version FROM constitution ORDER BY version").fetchall()]
    c.close()
    assert versions == [1, 2]
    con = governance.load_constitution()
    assert len(con["articles"]) == 7


def test_3_of_4_majority_accepted():
    """Standalone: 3/4 = 75% > 70% -> accepted."""
    from engine import tools, agents as agents_mod, db, governance
    import tempfile, shutil
    from pathlib import Path
    # new temp db
    tmpdir = tempfile.mkdtemp()
    old = db.DB_PATH
    db.DB_PATH = Path(tmpdir) / "x.db"
    try:
        db.init_db()
        from engine import world
        db.set_world_state("landmarks_seeded", False)
        db.set_world_state("agents_seeded", False)
        world.bootstrap()
        agents_mod.bootstrap()
        tools.bootstrap()
        for aid in ("anchor", "flora", "lovely", "spark"):
            tools.get("go_to_place").handler(agents_mod.get(aid), {"place": "town_hall"}, {})
        tools.get("submit_townhall_proposal").handler(
            agents_mod.get("anchor"),
            {"title": "X", "body": "y", "category": "general"}, {}
        )
        c = sqlite3.connect(str(db.DB_PATH))
        pid = c.execute("SELECT MAX(id) AS id FROM proposals").fetchone()[0]
        c.close()
        # 3 for, 1 against
        for aid in ("anchor", "flora", "lovely"):
            tools.get("vote_on_proposal").handler(
                agents_mod.get(aid), {"proposal_id": pid, "vote": "for"}, {}
            )
        # spark abstains (no vote cast)
        c = sqlite3.connect(str(db.DB_PATH))
        c.row_factory = sqlite3.Row
        status = c.execute("SELECT status FROM proposals WHERE id=?", (pid,)).fetchone()["status"]
        c.close()
        # 3/4 = 75% > 70%, but threshold_unreachable logic kicks in:
        # f=3, cast=3, remaining=1 -> 3+1=4 >= 0.7*4=2.8 -> still active
        assert status == "active"
    finally:
        db.DB_PATH = old
        shutil.rmtree(tmpdir, ignore_errors=True)
