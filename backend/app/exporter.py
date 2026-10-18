"""Deterministic, embedded-font print PDFs. QA findings distinguish proofs from publication-ready files."""

import io
import json
import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

import fitz
from PIL import Image
from reportlab.lib.colors import HexColor, white
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph
from sqlalchemy import select

from .models import (
    Chapter,
    ChapterSummary,
    Character,
    CharacterReference,
    Export,
    GenerationArtifact,
    Page,
    PageArtwork,
    PageLayoutElement,
    PageScript,
    QualityReport,
)
from .schemas import PrintSettings
from .storage import Storage

POINT = 72
FONT = "Alexandria"


def register_font():
    if FONT not in pdfmetrics.getRegisteredFontNames():
        import reportlab

        paths = [
            os.environ.get("BOOK_FONT_PATH", ""),
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            str(Path(reportlab.__file__).parent / "fonts/Vera.ttf"),
        ]
        path = next((p for p in paths if p and Path(p).is_file()), None)
        if not path:
            raise ValueError("Install a Unicode TrueType font or set BOOK_FONT_PATH")
        pdfmetrics.registerFont(TTFont(FONT, path))


def spine_width(page_count, paper):
    # KDP paperback factors, inches/page. Verify with KDP's current cover calculator before publication.
    return page_count * {"white": 0.002252, "cream": 0.0025, "color": 0.002347}[paper]


def gutter(page_count):
    return 0.375 if page_count <= 150 else 0.5 if page_count <= 300 else 0.625 if page_count <= 500 else 0.75


def page_dimensions(spec):
    return (spec.width + (0.125 if spec.bleed else 0)) * POINT, (
        spec.height + (0.25 if spec.bleed else 0)
    ) * POINT


def image_on_page(pdf, payload, rect, label, warnings, min_dpi=300):
    image = Image.open(io.BytesIO(payload))
    image.load()
    if image.mode != "RGB":
        rgba = image.convert("RGBA")
        image = Image.new("RGB", rgba.size, "white")
        image.paste(rgba, mask=rgba.getchannel("A"))
    x, y, width, height = rect
    scale = max(width / image.width, height / image.height)
    dw, dh = image.width * scale, image.height * scale
    dpi = POINT / scale
    if dpi + 0.01 < min_dpi:
        warnings.append(
            f"{label}: effective resolution {dpi:.0f} DPI is below {min_dpi}; no upscaling was applied"
        )
    pdf.saveState()
    path = pdf.beginPath()
    path.rect(x, y, width, height)
    pdf.clipPath(path, stroke=0)
    pdf.drawImage(
        ImageReader(image), x + (width - dw) / 2, y + (height - dh) / 2, width=dw, height=dh, mask=None
    )
    pdf.restoreState()
    return round(dpi, 2)


def text_box(pdf, text, rect, size, warnings, label, background=False):
    x, y, width, height = rect
    if not text.strip():
        return
    face = pdfmetrics.getFont(FONT).face
    unsupported = sorted(set(c for c in text if ord(c) > 32 and ord(c) not in face.charToGlyph))
    if unsupported:
        warnings.append(
            f"{label}: selected font lacks {len(unsupported)} glyph(s); install a suitable BOOK_FONT_PATH"
        )
    style = ParagraphStyle(
        "book", fontName=FONT, fontSize=size, leading=size * 1.35, textColor=HexColor("#222631")
    )
    paragraph = Paragraph(escape(text).replace("\n", "<br/>"), style)
    _, needed = paragraph.wrap(max(width - 12, 1), max(height - 12, 1))
    if needed > height - 12:
        warnings.append(f"{label}: text clipping ({needed:.0f}pt needed, {height - 12:.0f}pt available)")
    pdf.saveState()
    if background:
        pdf.setFillColor(white)
        pdf.roundRect(x, y, width, height, 5, stroke=0, fill=1)
    path = pdf.beginPath()
    path.rect(x, y, width, height)
    pdf.clipPath(path, stroke=0)
    paragraph.drawOn(pdf, x + 6, y + height - 6 - needed)
    pdf.restoreState()


def inspect_pdf(payload, expected_dimensions, expected_count):
    with fitz.open(stream=payload, filetype="pdf") as doc:
        dimensions_ok = all(
            abs(p.rect.width - expected_dimensions[0]) < 0.02
            and abs(p.rect.height - expected_dimensions[1]) < 0.02
            for p in doc
        )
        fonts = {f[0] for p in doc for f in p.get_fonts() if f[0] > 0}
        embedded = bool(fonts) and all(bool(doc.extract_font(xref)[3]) for xref in fonts)
        return dict(
            page_count=len(doc),
            dimensions_correct=dimensions_ok,
            count_correct=len(doc) == expected_count,
            embedded_fonts=embedded,
            bytes=len(payload),
        )


def contents_plan(chapters, pages, width, height, margin):
    """Paginate contents before calculating body page numbers and the cover spine."""
    register_font()
    first_pages = {}
    for index, page in enumerate(pages):
        first_pages.setdefault(page.chapter_id, index)
    front_matter = 3
    for _ in range(5):
        groups, used = [[]], 0
        for chapter in chapters:
            if chapter.id not in first_pages:
                continue
            entry = f"{chapter.title}  ·  {front_matter + 1 + first_pages[chapter.id]}"
            paragraph = Paragraph(
                escape(entry), ParagraphStyle("toc", fontName=FONT, fontSize=11, leading=14.85)
            )
            _, needed = paragraph.wrap(width - 2 * margin - 12, height)
            required = needed + 12
            if used + required > height - 2 * margin - 48 and groups[-1]:
                groups.append([])
                used = 0
            groups[-1].append((entry, required))
            used += required
        actual = 2 + len(groups)
        if actual == front_matter:
            return groups
        front_matter = actual
    return groups


def export_book(db, project):
    register_font()
    store = Storage()

    def rows(cls, **kw):
        return list(db.scalars(select(cls).filter_by(project_id=project.id, **kw)))

    pages = sorted(rows(Page), key=lambda p: p.position)
    if not pages or any(not p.current_artwork_id for p in pages):
        raise ValueError("Every page needs artwork before export; placeholders are never exported")
    if not project.cover.get("artwork_key"):
        raise ValueError("Cover artwork is required for a complete package")
    spec = PrintSettings.model_validate(project.config["print"])
    w, h = page_dimensions(spec)
    margin = spec.margin * POINT
    chapters = sorted(rows(Chapter), key=lambda c: c.position)
    contents = contents_plan(chapters, pages, w, h, margin)
    front_matter = 2 + len(contents)
    page_count = len(pages) + front_matter
    page_count += page_count % 2
    warnings, resolutions = [], {}
    offline = False
    if page_count < 24:
        warnings.append("KDP paperback requires at least 24 pages; this file is a proof")
    if page_count > 828:
        warnings.append("Page count exceeds standard paperback limits; verify selected trim/paper with KDP")
    if spec.paper == "cream" and (spec.width > 8.5 or spec.height > 11):
        warnings.append("Check trim and paper availability in KDP")
    if any(not c.locked for c in rows(Character)):
        warnings.append("One or more canonical character designs are not approved and locked")
    if not project.cover.get("artwork_approved"):
        warnings.append("Cover artwork is not approved")
    if any(not s.approved for s in rows(ChapterSummary)):
        warnings.append("Chapter summaries require approval")
    essential = {
        e["id"] for s in rows(ChapterSummary) for e in s.data.get("events", []) if e.get("essential")
    }
    covered = {eid for s in rows(PageScript) for eid in s.data.get("covered_event_ids", [])}
    if missing := essential - covered:
        warnings.append(
            f"Adaptation omits {len(missing)} essential source event(s); restore coverage before publication"
        )
    interior = io.BytesIO()
    pdf = canvas.Canvas(interior, pagesize=(w, h), pageCompression=1, initialFontName=FONT)
    pdf.setTitle(project.title)
    pdf.setAuthor(project.author)
    margin = spec.margin * POINT
    text_box(pdf, project.title, (margin, h * 0.58, w - 2 * margin, h * 0.24), 28, warnings, "Title")
    text_box(pdf, project.author, (margin, h * 0.43, w - 2 * margin, 60), 14, warnings, "Author")
    pdf.showPage()
    copyright_text = (
        f"{project.title}\nOriginal author: {project.author}\n"
        f"{project.cover.get('adaptation_credit', '')}\n{project.cover.get('publisher', '')}\n"
        f"Source edition: {project.config.get('edition', 'Unspecified')}\nRights declaration: {project.rights_declaration}\n"
        "Illustrations created with AI assistance. Verify adaptation, attribution, and market-specific rights before publication."
    )
    text_box(pdf, copyright_text, (margin, margin, w - 2 * margin, h - 2 * margin), 10, warnings, "Credits")
    pdf.showPage()
    for group in contents:
        text_box(
            pdf, "Contents", (margin, h - margin - 40, w - 2 * margin, 40), 18, warnings, "Contents heading"
        )
        top = h - margin - 48
        for entry, required in group:
            text_box(
                pdf,
                entry,
                (margin, top - required, w - 2 * margin, required),
                11,
                warnings,
                "Table of contents",
            )
            top -= required
        pdf.showPage()
    for i, page in enumerate(pages):
        art = db.get(PageArtwork, page.current_artwork_id)
        if not art or art.page_id != page.id:
            raise ValueError("Page has an invalid artwork association")
        script = rows(PageScript, page_id=page.id)[0]
        offline |= art.metadata_json.get("offline", False)
        if not page.approved or not script.approved:
            warnings.append(f"Page {i + front_matter + 1}: unapproved page or script")
        if art.metadata_json.get("script_version") != script.version:
            warnings.append(
                f"Page {i + front_matter + 1}: illustration is based on an earlier script version"
            )
        canonical = {
            f"{c.id}@{next((r.version for r in rows(CharacterReference) if r.id == c.approved_reference_id), 0)}"
            for c in rows(Character)
            if c.name in script.data["characters"]
        }
        if (
            canonical
            - set(art.metadata_json.get("reference_ids", []))
            - set(art.metadata_json.get("omitted_reference_ids", []))
            - set(art.metadata_json.get("qa_reference_ids", []))
        ):
            warnings.append(
                f"Page {i + front_matter + 1}: illustration predates the current canonical character references"
            )
        qa = next((a for a in rows(GenerationArtifact, stage="visual_qa") if a.artifact_key == art.id), None)
        if not qa or not qa.data.get("passed"):
            warnings.append(
                f"Page {i + front_matter + 1}: visual/narrative AI QA is incomplete or flagged issues"
            )
        if not script.data.get("source_passages"):
            warnings.append(f"Page {i + front_matter + 1}: missing source passage references")
        if spec.bleed:
            rect = (0, 0, w, h)
        else:
            inside = max(gutter(page_count), spec.margin) * POINT
            left = inside if (i + front_matter + 1) % 2 else margin
            rect = (left, margin, w - left - margin, h - 2 * margin)
        resolutions[page.id] = image_on_page(
            pdf, store.get(art.storage_key), rect, f"Page {i + front_matter + 1}", warnings, spec.minimum_dpi
        )
        for element in rows(PageLayoutElement, page_id=page.id):
            d = element.data
            x, y, bw, bh = d["x"] * w, (1 - d["y"] - d["height"]) * h, d["width"] * w, d["height"] * h
            safe_inside = max(gutter(page_count), spec.margin) * POINT
            if min(x, w - x - bw, y, h - y - bh) < min(margin, safe_inside) - 1:
                warnings.append(
                    f"Page {i + front_matter + 1}: text element may cross a print-safe margin or gutter"
                )
            text_box(
                pdf,
                d["text"],
                (x, y, bw, bh),
                d.get("font_size", 12),
                warnings,
                f"Page {i + front_matter + 1} {element.kind}",
                True,
            )
        pdf.showPage()
    if (len(pages) + front_matter) % 2:
        pdf.showPage()  # Intentional blank last page; deterministic even page count.
    pdf.save()
    payload = interior.getvalue()
    spine = spine_width(page_count, spec.paper)
    cw, ch = (2 * spec.width + spine + 0.25) * POINT, (spec.height + 0.25) * POINT
    cover_buffer = io.BytesIO()
    cover = canvas.Canvas(cover_buffer, pagesize=(cw, ch), pageCompression=1, initialFontName=FONT)
    cover.setTitle(project.title + " — wraparound cover")
    cover.setFillColor(HexColor("#18212d"))
    cover.rect(0, 0, cw, ch, stroke=0, fill=1)
    front_x = (0.125 + spec.width + spine) * POINT
    resolutions["cover"] = image_on_page(
        cover,
        store.get(project.cover["artwork_key"]),
        (front_x, 0, (spec.width + 0.125) * POINT, ch),
        "Front cover",
        warnings,
        spec.minimum_dpi,
    )
    offline |= project.cover.get("metadata", {}).get("offline", False)
    cover_data = project.cover
    text_box(
        cover,
        cover_data.get("title", project.title),
        (front_x + margin, ch * 0.70, spec.width * POINT - 2 * margin, ch * 0.20),
        25,
        warnings,
        "Cover title",
        True,
    )
    text_box(
        cover,
        cover_data.get("subtitle", "") + "\n" + cover_data.get("author", project.author),
        (front_x + margin, ch * 0.10, spec.width * POINT - 2 * margin, ch * 0.18),
        12,
        warnings,
        "Cover byline",
        True,
    )
    back_text = "\n\n".join(
        filter(
            None,
            [
                cover_data.get("back_text", ""),
                cover_data.get("adaptation_credit", ""),
                cover_data.get("series", ""),
                f"Volume {cover_data['volume']}" if cover_data.get("volume") else "",
                cover_data.get("publisher", ""),
            ],
        )
    )
    text_box(
        cover,
        back_text,
        (margin, ch * 0.25, spec.width * POINT - 2 * margin, ch * 0.60),
        12,
        warnings,
        "Back cover",
        True,
    )
    # Reserve the standard barcode area on back. KDP may place the barcode itself.
    cover.setFillColor(white)
    cover.rect((spec.width - 2.25) * POINT, 0.375 * POINT, 2 * POINT, 1.2 * POINT, stroke=0, fill=1)
    if page_count >= 79:
        cover.saveState()
        cover.translate((0.125 + spec.width + spine / 2) * POINT, ch / 2)
        cover.rotate(90)
        cover.setFont(FONT, min(12, max(6, spine * POINT * 0.6)))
        cover.setFillColor(white)
        cover.drawCentredString(0, -3, project.title[:100])
        cover.restoreState()
    cover.showPage()
    cover.save()
    cover_payload = cover_buffer.getvalue()
    if offline:
        warnings.append("OFFLINE TEST ART: these proofs must not be published")
    interior_check = inspect_pdf(payload, (w, h), page_count)
    cover_check = inspect_pdf(cover_payload, (cw, ch), 1)
    for label, check in [("Interior", interior_check), ("Cover", cover_check)]:
        if not all(check[k] for k in ("dimensions_correct", "count_correct", "embedded_fonts")):
            warnings.append(f"{label}: PDF structural validation failed")
    if len(payload) > 650 * 1024 * 1024:
        warnings.append("Interior exceeds 650 MB KDP limit")
    report = dict(
        publication_ready=not warnings,
        warnings=list(dict.fromkeys(warnings)),
        offline=offline,
        effective_dpi=resolutions,
        interior=interior_check,
        cover=cover_check,
    )
    manifest = dict(
        schema_version=1,
        created_at=datetime.now(timezone.utc).isoformat(),
        title=project.title,
        format="KDP paperback print proof",
        kindle_ready=False,
        page_count=page_count,
        trim=spec.model_dump(),
        spine_inches=round(spine, 6),
        interior_points=[w, h],
        cover_points=[cw, ch],
        qa=report,
        note="Validate current KDP paper/trim limits and cover calculator before publication. Costs are configured-rate accounting, not provider invoices.",
    )
    package = io.BytesIO()
    with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("interior.pdf", payload)
        archive.writestr("cover.pdf", cover_payload)
        archive.writestr("qa-report.json", json.dumps(report, indent=2))
        archive.writestr("manifest.json", json.dumps(manifest, indent=2))
    result = Export(
        project_id=project.id,
        interior_key=store.put(project.id, payload, "pdf", "application/pdf"),
        cover_key=store.put(project.id, cover_payload, "pdf", "application/pdf"),
        zip_key=store.put(project.id, package.getvalue(), "zip", "application/zip"),
        manifest=manifest,
    )
    db.add(result)
    db.flush()
    db.add(
        QualityReport(
            project_id=project.id, export_id=result.id, data=report, passed=report["publication_ready"]
        )
    )
    db.commit()
    return result
