# Parked design questions

Things we've deliberately deferred, with enough context to pick back up later.

## Reticle-select zoom on the card image (raised during detail-popup feedback)
Idea: let the user drag out a rectangle ("reticle") directly on the enlarged
card image and zoom specifically into that region, rather than only the
current whole-image wheel-zoom. Ctrl+click was suggested as the modifier to
distinguish "start a reticle selection" from "drag the window around" (plain
click+drag currently means "move the window"). Not designed yet -- open
questions when we get to it:
- Does the reticle zoom replace the current whole-image zoom, or layer on
  top of it (zoom into a region of an already-zoomed image)?
- Once real card images (not color placeholders) exist, is this pixel-crop
  based (crop + rescale a QPixmap region) or done via a transform on the
  view (translate + scale)? The former is simpler; the latter generalizes
  better if we ever want smooth pan/zoom animation.
- Should the reticle rectangle stay visible as an overlay while dragging it
  out (typical UX), and what cancels it (Escape, releasing outside the image)?

## Undo/redo + save model (raised during TreePane feedback pass)
Not designed yet. Rough shape of the open questions, for when we do:

- **In-memory edit history for Ctrl+Z/Ctrl+Y**, scoped to... what? Just tree
  edits (rename/move/delete/create)? Also table edits (checkbox toggles,
  qty changes) once those exist? A single global undo stack across the
  whole app is simpler for the user to reason about; per-view stacks are
  easier to implement in isolation but "undo" would need to mean "undo in
  whichever view has focus," which may or may not match what a user expects.
- **Explicit save vs. autosave.** You floated "only commit to files when the
  user explicitly saves" -- that implies an in-memory "dirty" working copy
  layered over whatever's on disk (or in SQLite), which has real implications
  for how the data layer gets designed once we build it (goal from the
  original outline: local JSON + SQLite). Worth deciding BEFORE the real
  database layer is built, not after, since retrofitting "everything is
  actually a diff against a committed state" onto an already-built direct-
  write data layer is a lot more painful than designing for it up front.
- **Auto-backup of database files** -- periodic snapshot/copy, probably
  independent of the undo/redo question above (backup protects against
  file corruption/loss; undo/redo protects against user mistakes mid-session).

Revisit once the real data layer (SQLite decks/tags/collection tables) is
underway -- this will shape how that layer is built, not just sit on top of it.
