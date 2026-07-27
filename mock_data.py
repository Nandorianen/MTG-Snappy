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
#
# New fields added for the spreadsheet view, and why each exists:
#   cmc              -> numeric mana value, so the Mana Cost column can sort numerically
#                       instead of alphabetically sorting the string "{1}{G}".
#   power / toughness-> kept as separate numbers (None for non-creatures) so P/T can sort
#                       numerically and we can format "power/toughness" for display.
#   qty              -> how many copies the user owns/wants; this is per-COLLECTION data,
#                       not really a property of the card itself -- in the real schema this
#                       will live in the inventory/wishlist database (goal #6), joined against
#                       the master card table, not stored on the card record. It's inlined here
#                       purely because we don't have that join yet.
#   selected         -> backs the row checkbox. Same caveat as qty: this is UI/collection
#                       state, not a card property, and will move once real DBs exist.
#   price_tcg/ck/cm  -> three mock "price source" values, standing in for the real pricing
#                       APIs a user might configure -- this is what the Price column's
#                       dropdown header will switch between.
MOCK_CARDS = [
    {
        "name": "Lightning Bolt", "mana_cost": "{R}", "cmc": 1,
        "type_line": "Instant", "colors": ["R"],
        "oracle_text": "Lightning Bolt deals 3 damage to any target.",
        "set": "LEA", "rarity": "common", "keywords": [],
        "power": None, "toughness": None,
        "price_tcg": 45.00, "price_ck": 39.99, "price_cm": 41.50,
    },
    {
        "name": "Swords to Plowshares", "mana_cost": "{W}", "cmc": 1,
        "type_line": "Instant", "colors": ["W"],
        "oracle_text": "Exile target creature. Its controller gains life equal to its power.",
        "set": "LEA", "rarity": "uncommon", "keywords": [],
        "power": None, "toughness": None,
        "price_tcg": 22.00, "price_ck": 19.50, "price_cm": 20.75,
    },
    {
        "name": "Tarmogoyf", "mana_cost": "{1}{G}", "cmc": 2,
        "type_line": "Creature — Lhurgoyf", "colors": ["G"],
        "oracle_text": (
            "Tarmogoyf's power is equal to the number of card types among cards in "
            "all graveyards and its toughness is equal to that number plus 1."
        ),
        "set": "FUT", "rarity": "rare", "keywords": [],
        "power": 4, "toughness": 5,
        "price_tcg": 38.00, "price_ck": 34.99, "price_cm": 36.20,
    },
    {
        "name": "Baleful Strix", "mana_cost": "{U}{B}", "cmc": 2,
        "type_line": "Artifact Creature — Bird", "colors": ["U", "B"],
        "oracle_text": "Flying, deathtouch. When Baleful Strix enters the battlefield, draw a card.",
        "set": "DGM", "rarity": "rare", "keywords": ["Flying", "Deathtouch"],
        "power": 1, "toughness": 1,
        "price_tcg": 6.00, "price_ck": 5.25, "price_cm": 5.75,
    },
    {
        "name": "Goblin Guide", "mana_cost": "{R}", "cmc": 1,
        "type_line": "Creature — Goblin Scout", "colors": ["R"],
        "oracle_text": (
            "Haste. Whenever Goblin Guide attacks, defending player reveals the top "
            "card of their library."
        ),
        "set": "ZEN", "rarity": "rare", "keywords": ["Haste"],
        "power": 2, "toughness": 2,
        "price_tcg": 18.00, "price_ck": 15.99, "price_cm": 16.80,
    },
    {
        "name": "Serra Angel", "mana_cost": "{3}{W}{W}", "cmc": 5,
        "type_line": "Creature — Angel", "colors": ["W"],
        "oracle_text": "Flying, vigilance.",
        "set": "LEA", "rarity": "uncommon", "keywords": ["Flying", "Vigilance"],
        "power": 4, "toughness": 4,
        "price_tcg": 12.00, "price_ck": 10.50, "price_cm": 11.25,
    },
    {
        "name": "Thragtusk", "mana_cost": "{3}{G}{G}", "cmc": 5,
        "type_line": "Creature — Beast", "colors": ["G"],
        "oracle_text": (
            "When Thragtusk enters the battlefield, you gain 5 life. When Thragtusk "
            "leaves the battlefield, create a 3/3 green Beast creature token."
        ),
        "set": "AVR", "rarity": "rare", "keywords": [],
        "power": 5, "toughness": 3,
        "price_tcg": 3.50, "price_ck": 2.99, "price_cm": 3.10,
    },
    {
        "name": "Thalia, Guardian of Thraben", "mana_cost": "{1}{W}", "cmc": 2,
        "type_line": "Legendary Creature — Human Soldier", "colors": ["W"],
        "oracle_text": "First strike. Noncreature spells cost {1} more to cast.",
        "set": "ISD", "rarity": "rare", "keywords": ["First strike"],
        "power": 2, "toughness": 1,
        "price_tcg": 8.00, "price_ck": 6.99, "price_cm": 7.40,
    },
]

RARITY_ORDER = {"common": 0, "uncommon": 1, "rare": 2, "mythic": 3}


def _with_collection_fields(cards, qty_values):
    """
    Returns deep-enough copies of the mock cards with per-collection fields
    (qty, selected) attached. Deep copy matters here because inventory and
    wishlist need INDEPENDENT qty/selected state for the same underlying card
    -- if we didn't copy, checking a box in Inventory would incorrectly also
    check it in Wishlist, since both would point at the same dict.
    """
    result = []
    for card, qty in zip(cards, qty_values):
        card_copy = dict(card)
        card_copy["qty"] = qty
        card_copy["selected"] = False
        result.append(card_copy)
    return result


def get_inventory_cards():
    """Mock 'owned copies' dataset -- stand-in for a real inventory DB query."""
    qty_values = [4, 1, 2, 1, 3, 1, 2, 1]
    return _with_collection_fields(MOCK_CARDS, qty_values)


def get_wishlist_cards():
    """Mock 'wanted copies' dataset -- stand-in for a real wishlist DB query."""
    qty_values = [1, 2, 1, 1, 1, 1, 1, 1]
    return _with_collection_fields(MOCK_CARDS, qty_values)


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


# ---------------------------------------------------------------------------
# Card detail data: editions, legalities, rulings.
#
# ARCHITECTURE NOTE: a row in the Inventory/Wishlist table represents ONE
# owned/wanted COPY of a card IN A SPECIFIC PRINTING (that's what "set" and
# "rarity" on a MOCK_CARDS entry mean). The card detail popup needs something
# different: the FULL print history for that card NAME, independent of which
# copy you happen to own. In the real schema this is exactly the difference
# between a "prints" table (one row per set the card was ever printed in,
# keyed by a shared oracle/card-name id) and a "collection" table (one row
# per copy a user owns, referencing a specific print). CARD_PRINTS below
# stands in for that prints table; MOCK_CARDS stands in for the collection
# table. Two cards below (Lightning Bolt, Swords to Plowshares) get a second
# printing so the edition-switcher dropdown has something real to switch
# between; the rest fall back to a single print derived from their
# MOCK_CARDS entry via get_card_prints() below.
CARD_PRINTS = {
    "Lightning Bolt": [
        {"set": "LEA", "rarity": "common",
         "flavor_text": "A red mage's first and favorite lesson.",
         "price_tcg": 45.00, "price_ck": 39.99, "price_cm": 41.50},
        {"set": "2XM", "rarity": "common",
         "flavor_text": "Simple, direct, and always in style.",
         "price_tcg": 3.50, "price_ck": 2.99, "price_cm": 3.10},
    ],
    "Swords to Plowshares": [
        {"set": "LEA", "rarity": "uncommon",
         "flavor_text": "Those who beat their swords into plowshares will plow for those who don't.",
         "price_tcg": 22.00, "price_ck": 19.50, "price_cm": 20.75},
        {"set": "DMR", "rarity": "rare",
         "flavor_text": "Peace, at a cost.",
         "price_tcg": 8.00, "price_ck": 6.50, "price_cm": 7.10},
    ],
}

# Formats tracked for the Legality tab. This list and the statuses below are
# illustrative/mock -- NOT accurate real-world legality data -- purely to
# exercise the UI.
FORMATS = ["Standard", "Pioneer", "Modern", "Legacy", "Vintage", "Commander", "Pauper"]
_DEFAULT_LEGALITY = {fmt: "not_legal" for fmt in FORMATS}


def _legal_in(*formats):
    result = dict(_DEFAULT_LEGALITY)
    for fmt in formats:
        result[fmt] = "legal"
    return result


CARD_LEGALITIES = {
    "Lightning Bolt": _legal_in("Modern", "Legacy", "Vintage", "Commander", "Pauper"),
    "Swords to Plowshares": _legal_in("Legacy", "Vintage", "Commander"),
    "Tarmogoyf": _legal_in("Modern", "Legacy", "Vintage", "Commander"),
    "Baleful Strix": _legal_in("Modern", "Legacy", "Vintage", "Commander"),
    "Goblin Guide": _legal_in("Modern", "Legacy", "Vintage", "Commander"),
    "Serra Angel": _legal_in("Pioneer", "Modern", "Legacy", "Vintage", "Commander"),
    "Thragtusk": _legal_in("Pioneer", "Modern", "Legacy", "Vintage", "Commander"),
    "Thalia, Guardian of Thraben": _legal_in("Modern", "Legacy", "Vintage", "Commander"),
}

# Short, ORIGINALLY-WRITTEN mock rulings (not transcribed from any real
# Gatherer/Scryfall ruling text) -- purely to give the Rulings tab something
# to scroll through.
CARD_RULINGS = {
    "Lightning Bolt": [
        "Lightning Bolt can target a player, a creature, a planeswalker, or a battle.",
        "The damage is dealt when the spell resolves, not when it's cast.",
    ],
    "Swords to Plowshares": [
        "The life gained is based on the creature's power as it last existed on the battlefield.",
        "If the creature has no power (or negative power), its controller gains no life.",
    ],
    "Tarmogoyf": [
        "Card types in graveyards are counted regardless of whose graveyard they're in.",
        "An empty graveyard means Tarmogoyf is a 0/1.",
    ],
    "Baleful Strix": [
        "The draw trigger happens once, when Baleful Strix enters the battlefield.",
    ],
    "Goblin Guide": [
        "The revealed card is not exiled or discarded -- it's just shown, then returned to the library.",
    ],
    "Serra Angel": [],
    "Thragtusk": [
        "Both triggered abilities happen no matter how Thragtusk leaves the battlefield.",
    ],
    "Thalia, Guardian of Thraben": [
        "The cost increase applies once per noncreature spell, not per instance of Thalia if there are multiples.",
    ],
}


def get_card_by_name(name):
    """Looks up the oracle-level record (name/type/mana cost/text/etc.) by name."""
    for card in MOCK_CARDS:
        if card["name"] == name:
            return card
    return None


def get_card_prints(name):
    """
    Full print history for a card name. Falls back to a single print derived
    from the card's own MOCK_CARDS entry if we haven't hand-authored a
    multi-print list for it above.
    """
    if name in CARD_PRINTS:
        return CARD_PRINTS[name]
    card = get_card_by_name(name)
    if card is None:
        return []
    return [{
        "set": card["set"], "rarity": card["rarity"],
        "flavor_text": "",
        "price_tcg": card["price_tcg"], "price_ck": card["price_ck"], "price_cm": card["price_cm"],
    }]


def get_card_legalities(name):
    return CARD_LEGALITIES.get(name, dict(_DEFAULT_LEGALITY))


def get_card_rulings(name):
    return CARD_RULINGS.get(name, [])


# Mock price sources, standing in for real pricing API configuration. Lives
# here (not in card_table.py) because it's data, and both card_table.py
# (the Price column header) and card_detail_popup.py (the Price stat field)
# need it -- keeping it in mock_data avoids either view module importing
# from the other.
PRICE_SOURCES = [
    ("price_tcg", "TCGplayer"),
    ("price_ck", "Card Kingdom"),
    ("price_cm", "Cardmarket"),
]
