"""
mock_data.py
------------
Stand-in for the real data layer we'll build later (Scryfall bulk import -> SQLite).

Why a separate module at all, for something this small? Because when we DO replace
this with real SQLite queries, the rest of the app (main_window.py) should not need
to change AT ALL — it just calls get_all_cards() and gets back the same shape of
data (a list of dicts). This is the "swap the engine, keep the interface" idea:
as long as the function signature and return shape stay the same, main.py never
needs to know or care where the cards actually came from.

Each dict mirrors a *subset* of real Scryfall fields, using the same key names
Scryfall uses (name, mana_cost, type_line, oracle_text, colors, set, rarity) so that
when we do the real import later, we're not renaming fields for no reason.
"""

# Each "colors" list uses Scryfall's mana color letters: W, U, B, R, G (and [] for colorless).
# We use this to pick a placeholder swatch color for the "art" box, since we don't have
# real card images yet -- just a rough visual stand-in so the layout isn't blank gray boxes.
MOCK_CARDS = [
    {
        "name": "Lightning Bolt",
        "mana_cost": "{R}",
        "type_line": "Instant",
        "colors": ["R"],
        "oracle_text": "Lightning Bolt deals 3 damage to any target.",
        "set": "LEA",
        "rarity": "common",
        "keywords": [],
    },
    {
        "name": "Swords to Plowshares",
        "mana_cost": "{W}",
        "type_line": "Instant",
        "colors": ["W"],
        "oracle_text": (
            "Exile target creature. Its controller gains life equal to its power."
        ),
        "set": "LEA",
        "rarity": "uncommon",
        "keywords": [],
    },
    {
        "name": "Tarmogoyf",
        "mana_cost": "{1}{G}",
        "type_line": "Creature — Lhurgoyf",
        "colors": ["G"],
        "oracle_text": (
            "Tarmogoyf's power is equal to the number of card types among cards in "
            "all graveyards and its toughness is equal to that number plus 1."
        ),
        "set": "FUT",
        "rarity": "rare",
        "keywords": [],
    },
    {
        "name": "Baleful Strix",
        "mana_cost": "{U}{B}",
        "type_line": "Artifact Creature — Bird",
        "colors": ["U", "B"],
        "oracle_text": (
            "Flying, deathtouch. When Baleful Strix enters the battlefield, draw a card."
        ),
        "set": "DGM",
        "rarity": "rare",
        "keywords": ["Flying", "Deathtouch"],
    },
    {
        "name": "Goblin Guide",
        "mana_cost": "{R}",
        "type_line": "Creature — Goblin Scout",
        "colors": ["R"],
        "oracle_text": (
            "Haste. Whenever Goblin Guide attacks, defending player reveals the top "
            "card of their library."
        ),
        "set": "ZEN",
        "rarity": "rare",
        "keywords": ["Haste"],
    },
    {
        "name": "Serra Angel",
        "mana_cost": "{3}{W}{W}",
        "type_line": "Creature — Angel",
        "colors": ["W"],
        "oracle_text": "Flying, vigilance.",
        "set": "LEA",
        "rarity": "uncommon",
        "keywords": ["Flying", "Vigilance"],
    },
    {
        "name": "Thragtusk",
        "mana_cost": "{3}{G}{G}",
        "type_line": "Creature — Beast",
        "colors": ["G"],
        "oracle_text": (
            "When Thragtusk enters the battlefield, you gain 5 life. When Thragtusk "
            "leaves the battlefield, create a 3/3 green Beast creature token."
        ),
        "set": "AVR",
        "rarity": "rare",
        "keywords": [],
    },
    {
        "name": "Thalia, Guardian of Thraben",
        "mana_cost": "{1}{W}",
        "type_line": "Legendary Creature — Human Soldier",
        "colors": ["W"],
        "oracle_text": (
            "First strike. Noncreature spells cost {1} more to cast."
        ),
        "set": "ISD",
        "rarity": "rare",
        "keywords": ["First strike"],
    },
]


# Rough placeholder swatch colors per mana color, purely for visual variety
# in the "art box" stand-in until real card images are wired up.
COLOR_SWATCHES = {
    "W": "#F8F4E3",
    "U": "#0E68AB",
    "B": "#3B3A30",
    "R": "#D3202A",
    "G": "#00733E",
}
MULTICOLOR_SWATCH = "#C9A227"
COLORLESS_SWATCH = "#8A8D8F"


def get_all_cards():
    """
    Returns the full mock card list.

    This is the ONE function main_window.py calls to get card data. When we build
    the real data layer, this function gets reimplemented to run a SQL query
    against SQLite instead -- e.g. `SELECT * FROM cards` -- but the return shape
    (list of dicts with these same keys) stays identical, so nothing upstream breaks.
    """
    return MOCK_CARDS


def swatch_for_card(card):
    """Pick a placeholder color based on a card's color identity."""
    colors = card.get("colors", [])
    if len(colors) == 0:
        return COLORLESS_SWATCH
    if len(colors) > 1:
        return MULTICOLOR_SWATCH
    return COLOR_SWATCHES.get(colors[0], COLORLESS_SWATCH)
