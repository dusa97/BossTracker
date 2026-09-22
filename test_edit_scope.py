"""Past-week edits must not silently bleed forward: _edit_scope asks, and
"This Week Only" pins the following week so inheritance stops there."""
from datetime import date, datetime, timedelta

import main
from main import BossTrackerApp as App

BOSS = "boss/Lotus.png"
CUR_THU = date(2026, 9, 17)
PAST = "2026-08-06"


class FakeBox:
    """Stands in for QMessageBox; `choice` picks which button was clicked."""
    choice = 0
    Icon = type("I", (), {"Question": 0})
    ButtonRole = type("R", (), {"AcceptRole": 0})
    StandardButton = type("S", (), {"Cancel": 1})

    def __init__(self, parent=None):
        self.buttons = []

    def __getattr__(self, _name):          # setText / setIcon / setStyleSheet / exec
        return lambda *a, **k: None

    def addButton(self, *a):
        b = object()
        self.buttons.append(b)
        return b

    def clickedButton(self):
        return self.buttons[FakeBox.choice]


def make_app():
    app = App.__new__(App)
    app._resolve_cache = {}
    app.actual_current_thursday = CUR_THU
    app.actual_current_week_key = CUR_THU.strftime("%Y-%m-%d")
    app.saved_boss_clears = {
        (1, PAST): [{"path": BOSS, "difficulty": "Normal", "party_size": 1, "is_deleted_marker": False}]
    }
    return app


def weeks_from(start, count):
    d = datetime.strptime(start, "%Y-%m-%d").date()
    return [(d + timedelta(weeks=i)).strftime("%Y-%m-%d") for i in range(count)]


def difficulty_at(app, wkey):
    app._resolve_cache.clear()
    state, _ = app.resolve_boss_state_at_week(1, wkey, BOSS)
    return state and state["difficulty"]


def apply_difficulty(app, wkey, new_diff):
    state, _ = app.resolve_boss_state_at_week(1, wkey, BOSS)
    for apply_wkey, ws in app._edit_scope(1, wkey, BOSS, state):
        app._upsert_stamp(1, apply_wkey, BOSS, {"party_size": ws.get("party_size", 1)},
                          difficulty=new_diff, is_deleted_marker=False)
    app._resolve_cache.clear()


def test_inheritance_baseline():
    app = make_app()
    for wk in weeks_from(PAST, 6):
        assert difficulty_at(app, wk) == "Normal", wk


def test_run_spans_to_current_week():
    app = make_app()
    state, _ = app.resolve_boss_state_at_week(1, PAST, BOSS)
    run = app._forward_run(1, PAST, BOSS, state)
    assert run[0][0] == PAST
    assert run[-1][0] == app.actual_current_week_key


def test_this_week_only_stops_the_bleed():
    app, FakeBox.choice = make_app(), 0          # "This Week Only"
    main.QMessageBox = FakeBox
    apply_difficulty(app, PAST, "Hard")
    assert difficulty_at(app, PAST) == "Hard"
    for wk in weeks_from(PAST, 6)[1:]:
        assert difficulty_at(app, wk) == "Normal", wk
    assert difficulty_at(app, app.actual_current_week_key) == "Normal"


def test_all_weeks_still_propagates():
    app, FakeBox.choice = make_app(), 1          # "All N Weeks"
    main.QMessageBox = FakeBox
    apply_difficulty(app, PAST, "Hard")
    for wk in weeks_from(PAST, 6):
        assert difficulty_at(app, wk) == "Hard", wk
    assert difficulty_at(app, app.actual_current_week_key) == "Hard"


def test_cancel_changes_nothing():
    app, FakeBox.choice = make_app(), 2          # Cancel
    main.QMessageBox = FakeBox
    apply_difficulty(app, PAST, "Hard")
    for wk in weeks_from(PAST, 6):
        assert difficulty_at(app, wk) == "Normal", wk


def test_current_week_edit_never_prompts():
    app = make_app()
    main.QMessageBox = None                      # touching it would raise
    cur = app.actual_current_week_key
    state, _ = app.resolve_boss_state_at_week(1, cur, BOSS)
    assert app._edit_scope(1, cur, BOSS, state) == [(cur, state)]


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
    print("all passed")
