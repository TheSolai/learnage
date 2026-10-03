"""Per-tab views that live inside BookWindow or the launcher.

Extracted from gui/app.py and gui/book_window.py in v2.0. Each view is its
own QWidget — Compose View, ReadView, etc. — so BookWindow can stay a thin
shell that just wires tabs.

Currently:
- soul.py     — SoulView (the launcher's "souls" section body)
- read.py     — ReadView (the launcher's read-preview for a book)
"""