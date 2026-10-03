"""Cover thumbnail extraction and rendering."""

from __future__ import annotations

import hashlib
import io
import subprocess
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter, QPixmap


CACHE_DIR = Path.home() / ".learnage" / "covers"


def _hash_path(p: Path) -> str:
    return hashlib.sha1(str(p).encode()).hexdigest()[:16]


def cover_path_for(source_path: str | Path) -> Path:
    return CACHE_DIR / f"{_hash_path(Path(source_path))}.png"


# --------------------------------------------------------------------- extraction


def extract_epub_cover(epub_path: Path, dest: Path) -> bool:
    """Extract the embedded cover image from an EPUB."""
    try:
        from ebooklib import epub, ITEM_COVER, ITEM_IMAGE

        book = epub.read_epub(str(epub_path), options={"ignore_ncx": True})
        # Preferred: ITEM_COVER
        for item in book.get_items_of_type(ITEM_COVER):
            data = item.get_content()
            if data:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
                return True
        # Fallback: first image named cover/cover.*
        for item in book.get_items_of_type(ITEM_IMAGE):
            name = (item.get_name() or "").lower()
            if "cover" in name:
                data = item.get_content()
                if data:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(data)
                    return True
        # Last resort: first image
        for item in book.get_items_of_type(ITEM_IMAGE):
            data = item.get_content()
            if data and item.get_content_type() in ("image/jpeg", "image/png"):
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
                return True
    except Exception:  # noqa: BLE001
        pass
    return False


def extract_pdf_cover(pdf_path: Path, dest: Path, *, size: int = 800) -> bool:
    """Render the first page of a PDF as a JPEG using `sips` (macOS).

    Faster than pulling in a heavy PDF rasterizer; uses the built-in macOS tool.
    Returns False if sips isn't available or fails.
    """
    try:
        subprocess.run(
            [
                "sips",
                "-s",
                "format",
                "jpeg",
                "-Z",
                str(size),
                str(pdf_path),
                "--out",
                str(dest),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=20,
        )
        return dest.exists()
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return False


# --------------------------------------------------------------------- rendering


def _render_placeholder(text: str, *, kind: str) -> QPixmap:
    """Render a beautiful placeholder cover with title + format icon."""
    pix = QPixmap(QSize(120, 180))
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)

    palettes = {
        "epub": (QColor("#3b1d52"), QColor("#7a3ca6"), QColor("#c084fc")),
        "pdf":  (QColor("#1e293b"), QColor("#334155"), QColor("#94a3b8")),
        "docx": (QColor("#1e3a52"), QColor("#2563eb"), QColor("#60a5fa")),
        "txt":  (QColor("#1f2937"), QColor("#374151"), QColor("#9ca3af")),
    }
    c1, c2, c3 = palettes.get(kind, palettes["epub"])

    from PySide6.QtGui import QLinearGradient
    grad = QLinearGradient(0, 0, 120, 180)
    grad.setColorAt(0, c1)
    grad.setColorAt(1, c2)
    p.fillRect(0, 0, 120, 180, grad)

    p.setPen(Qt.NoPen)
    p.setBrush(c3)
    p.setOpacity(0.18)
    p.drawEllipse(40, 110, 140, 140)
    p.setOpacity(1.0)

    p.setBrush(Qt.NoBrush)
    pen = p.pen()
    pen.setColor(QColor(255, 255, 255, 30))
    pen.setWidth(2)
    p.setPen(pen)
    p.drawRoundedRect(2, 2, 116, 176, 6, 6)

    p.setPen(QColor(255, 255, 255, 220))
    font = QFontDatabase.systemFont(QFontDatabase.GeneralFont)
    font.setPointSize(38)
    font.setBold(True)
    p.setFont(font)
    glyph = {"epub": "✦", "pdf": "▤", "docx": "✎", "txt": "✎"}.get(kind, "✦")
    p.drawText(pix.rect().adjusted(0, 24, 0, 0), Qt.AlignHCenter | Qt.AlignTop, glyph)

    font.setPointSize(10)
    font.setBold(False)
    p.setFont(font)
    p.setPen(QColor(255, 255, 255, 230))
    from PySide6.QtCore import QRect
    p.drawText(QRect(10, 130, 100, 50), Qt.AlignCenter | Qt.TextWordWrap, _truncate(text, 60))

    p.end()
    return pix


def _truncate(s: str, n: int) -> str:
    s = s.strip()
    if len(s) <= n:
        return s
    return s[: n - 1].rstrip() + "…"


def _load_from_disk(path: Path, target: QSize) -> QPixmap | None:
    img = QImage(str(path))
    if img.isNull():
        return None
    pix = QPixmap.fromImage(img)
    if pix.isNull():
        return None
    # Scale preserving aspect ratio to fill cover area
    return pix.scaled(target, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)


def extract_or_placeholder(
    book: dict, fmt: str, source_path: str | Path | None = None, *, size: QSize | None = None
) -> QPixmap:
    """Return a cover pixmap — extracted from EPUB/PDF if possible, else placeholder."""
    target = size or QSize(120, 180)
    if source_path:
        cp = cover_path_for(source_path)
        if cp.exists():
            pix = _load_from_disk(cp, target)
            if pix is not None:
                return pix
        # First-time: try to extract
        sp = Path(source_path)
        tmp = cp.with_suffix(".tmp")
        try:
            if sp.suffix.lower() == ".epub":
                extract_epub_cover(sp, tmp)
            elif sp.suffix.lower() == ".pdf":
                extract_pdf_cover(sp, tmp)
            if tmp.exists() and tmp.stat().st_size > 0:
                # Resize to a reasonable max
                pix = _load_from_disk(tmp, QSize(400, 600))
                if pix is not None:
                    CACHE_DIR.mkdir(parents=True, exist_ok=True)
                    pix.save(str(cp), "PNG")
                    tmp.unlink(missing_ok=True)
                    return pix
        except Exception:  # noqa: BLE001
            pass
        finally:
            if tmp.exists():
                tmp.unlink(missing_ok=True)

    title = book.get("title") or (Path(source_path).stem if source_path else "Untitled")
    pix = _render_placeholder(title, kind=fmt or "epub")
    if source_path:
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            pix.save(str(cover_path_for(source_path)), "PNG")
        except Exception:  # noqa: BLE001
            pass
    return pix
