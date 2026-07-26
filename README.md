# MTG Local Database — Prototype (UI shell)

## What this is
A minimal, working PySide6 window with the three-panel layout the real app
will use: tag tree (left) | card list + search (center) | card detail (right).
It runs against `mock_data.py` (8 hardcoded cards) instead of a real database —
that comes next.

## Run it
```bash
pip install PySide6
python main.py
```

## Try
- Type in the search box — the list filters live by name.
- Click a card, or use arrow keys after clicking into the list — the detail
  panel on the right updates.
- `Ctrl+F` — jump focus to the search box from anywhere in the window.
- `Ctrl+T` — toggle the tag panel's visibility.
- Drag the dividers between panels to resize them.
- `File > Import/Export` — present but intentionally stubbed (shows a dialog
  saying so) since there's no data layer wired up yet.

## What's deliberately NOT here yet
- Real card images (the colored box in the detail panel is a placeholder,
  colored by the card's mana color identity).
- Any real database — `mock_data.get_all_cards()` is the one function that
  will get swapped out for a SQLite query later; nothing else should need
  to change when that happens.
- Tag filtering logic (the tag tree is visible but not wired to anything).
