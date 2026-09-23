"""Custom items must behave like built-in drops: merged onto every difficulty of each
boss they are tied to, and fully removable without disturbing the built-in table."""
import copy

import main
from main import BossTrackerApp as App

BUILTIN = copy.deepcopy(main._BUILTIN_BOSS_DROPS)


def make_app(items):
    app = App.__new__(App)
    app.custom_items = items
    app._resolve_cache = {}
    app._stats_dirty = False
    app.items_shelf_layout = None
    return app


def test_builtin_table_is_untouched_with_no_custom_items():
    make_app([])._apply_custom_items()
    assert main.BOSS_DROPS == BUILTIN


def test_item_lands_on_every_difficulty_of_every_chosen_boss():
    make_app([{"name": "My Relic", "file": "My Relic.png", "bosses": ["kalos", "limbo"]}])._apply_custom_items()
    for boss in ("kalos", "limbo"):
        tiers = main.BOSS_DIFFICULTY_MAP[boss]
        assert tiers, boss
        for diff in tiers:
            assert "My Relic" in main.BOSS_DROPS[(boss, diff)], (boss, diff)
    # and nowhere else
    for (boss, _d), drops in main.BOSS_DROPS.items():
        if boss not in ("kalos", "limbo"):
            assert "My Relic" not in drops, boss


def test_builtin_drops_survive_the_merge():
    make_app([{"name": "My Relic", "file": "My Relic.png", "bosses": ["kalos"]}])._apply_custom_items()
    for key, drops in BUILTIN.items():
        assert set(drops) <= set(main.BOSS_DROPS[key]), key
    assert main.BOSS_DROPS[("seren", "Hard")] == BUILTIN[("seren", "Hard")]


def test_multiple_items_on_one_boss():
    make_app([{"name": "Relic A", "file": "a.png", "bosses": ["jupiter"]},
              {"name": "Relic B", "file": "b.png", "bosses": ["jupiter"]}])._apply_custom_items()
    drops = main.BOSS_DROPS[("jupiter", "Normal")]
    assert "Relic A" in drops and "Relic B" in drops
    assert "Grindstone of Faith" in drops


def test_removing_restores_the_builtin_table_exactly():
    items = [{"name": "My Relic", "file": "My Relic.png", "bosses": ["kalos", "limbo"]}]
    app = make_app(items)
    app._apply_custom_items()
    assert main.BOSS_DROPS != BUILTIN
    items.clear()
    app._apply_custom_items()
    assert main.BOSS_DROPS == BUILTIN
    assert not main.CUSTOM_CATEGORY_NAMES


def test_custom_category_gets_the_name_for_shelf_grouping():
    make_app([{"name": "My Relic", "file": "My Relic.png", "bosses": ["kalos"]}])._apply_custom_items()
    assert "my relic" in main.CUSTOM_CATEGORY_NAMES
    cats = {c for c, _col, _n in main.ITEM_CATEGORIES}
    assert "Custom" in cats and "Others" in cats


def test_unknown_boss_key_does_not_crash():
    make_app([{"name": "Ghost", "file": "g.png", "bosses": ["not-a-boss"]}])._apply_custom_items()
    assert "Ghost" in main.BOSS_DROPS[("not-a-boss", "Normal")]


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok", name)
    make_app([])._apply_custom_items()   # leave the table clean
    print("all passed")
