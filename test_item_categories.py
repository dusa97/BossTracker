"""Every list that enumerates items must agree about the Brilliant five.

These lists live apart (shelf category, pitched tracker, boss drop table) and drifted
once already, so this pins them together.
"""
import os

import main

BRILLIANT = {"blissful nightmare", "whisper of the source", "oath of death",
             "immortal legacy", "original sin of pride"}


def category(name):
    return next(n for c, _col, n in main.ITEM_CATEGORIES if c == name)


def test_brilliant_category_is_exactly_the_five():
    assert category("Brilliant") == BRILLIANT


def test_all_five_are_selectable_in_the_pitched_tracker():
    pitched = {n.lower() for n, _f in main.PITCHED_ITEMS}
    assert BRILLIANT <= pitched, BRILLIANT - pitched


def test_all_five_are_dropped_by_some_boss():
    dropped = {d.lower() for drops in main.BOSS_DROPS.values() for d in drops}
    assert BRILLIANT <= dropped, BRILLIANT - dropped


def test_every_pitched_entry_has_its_icon_file():
    missing = [f for _n, f in main.PITCHED_ITEMS
               if not os.path.exists(os.path.join(main.ITEMS_ASSETS_DIR, f))]
    assert not missing, missing


def test_every_drop_name_has_an_icon_file():
    assets = {os.path.splitext(f)[0].lower() for f in os.listdir(main.ITEMS_ASSETS_DIR)}
    missing = sorted({d for drops in main.BOSS_DROPS.values() for d in drops
                      if d.lower() not in assets})
    assert not missing, missing


def test_categories_do_not_overlap():
    seen = set()
    for cat, _col, names in main.ITEM_CATEGORIES[:-1]:
        clash = seen & names
        assert not clash, (cat, clash)
        seen |= names


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok", name)
    print("all passed")
