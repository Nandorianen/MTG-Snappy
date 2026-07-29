"""
tag_assignments.py
-------------------
A simple in-memory store mapping card name -> set of tag ids. Stand-in for
the tag-assignment database table from the original spec (goal #5's "yet
another separate database... categories (tags) that user assigns to
cards") -- when a real SQLite layer exists, this becomes a join table
(card_id, tag_id) instead of a module-level dict, but every caller here
goes through these four functions, so swapping the storage later doesn't
touch any calling code.

KEYED BY TAG ID, NOT TAG NAME. This matters: renaming a tag (F2 in the Tag
Database) must not orphan existing assignments. Tag ids are stable across
renames (see tree_pane.py -- an item's node dict keeps the same "id" for
its whole lifetime; only its display text changes on rename), so keying by
id here means a rename never breaks anything a card was already tagged with.
"""

_card_tags = {}  # card_name -> set(tag_id)


def tags_for_card(card_name):
    """Read-only snapshot of a card's current tag ids."""
    return set(_card_tags.get(card_name, set()))


def add_tag(card_name, tag_id):
    _card_tags.setdefault(card_name, set()).add(tag_id)


def remove_tag(card_name, tag_id):
    if card_name in _card_tags:
        _card_tags[card_name].discard(tag_id)


def cards_with_tag(tag_id):
    """Every card name currently carrying this tag id -- useful later for
    the Tag Database's 'click a tag, see its cards' view."""
    return {name for name, tags in _card_tags.items() if tag_id in tags}
