"""Conservative figure-label replacement, keeping all other PDF content."""
from __future__ import annotations

import io
import json
from pathlib import Path

import cv2
import numpy as np
import pymupdf as fitz
from PIL import Image

from .core import check_cancel, crop, manifest, pix_array


def clean_raster_label(page, bbox, dpi=300):
    """Repair only foreground glyph pixels; decline uncertain backgrounds/lines."""
    box = fitz.Rect(bbox)
    clip = (box + (-1, -1, 1, 1)) & page.rect
    pix = crop(page, clip, dpi)
    image = pix_array(pix)
    h, w = image.shape[:2]
    if h < 4 or w < 4:
        return None, "标签区域过小"
    border = np.concatenate([image[0], image[-1], image[:, 0], image[:, -1]])
    background = np.median(border, axis=0)
    distances = np.max(np.abs(border.astype(float) - background), axis=1)
    if np.mean(distances < 25) < 0.75:
        return None, "背景复杂，保留原文等待校正"
    difference = np.max(np.abs(image.astype(float) - background), axis=2)
    foreground = (difference > 30).astype(np.uint8)
    count, components, stats, _ = cv2.connectedComponentsWithStats(foreground, 8)
    mask = np.zeros((h, w), np.uint8)
    for i in range(1, count):
        x, y, cw, ch, area = stats[i]
        if area < 2:
            continue
        edge = x == 0 or y == 0 or x + cw == w or y + ch == h
        # An uppercase I is tall and narrow too: only flag strokes spanning
        # the crop boundary, not isolated slender glyphs inside the OCR box.
        line = ((cw > w * 0.9 and cw > ch * 6) or (ch > h * 0.9 and ch > cw * 6)) and edge
        if line or (edge and (cw > w * 0.7 or ch > h * 0.95)):
            return None, "文字区域与边框或线条交叠，保留原文"
        mask[components == i] = 255
    if not mask.any() or np.mean(mask > 0) > 0.6:
        return None, "无法可靠分离字形"
    mask = cv2.dilate(mask, np.ones((3, 3), np.uint8))
    image[mask > 0] = background.astype(np.uint8)
    stream = io.BytesIO()
    Image.fromarray(image).save(stream, format="PNG")
    actual_rect = fitz.Rect(pix.x / (dpi / 72), pix.y / (dpi / 72),
                            (pix.x + pix.width) / (dpi / 72), (pix.y + pix.height) / (dpi / 72))
    return (stream.getvalue(), actual_rect), ""


def prepare_text(overlay, label, figure_box):
    box = fitz.Rect(label.bbox) & fitz.Rect(figure_box)
    # Fixed text bounds avoid intruding into neighboring modules or arrows.
    size = min(14, label.size, box.height * 0.8)
    while size >= 4.5:
        remaining = overlay.insert_textbox(box, label.translation, fontsize=size, fontname="china-s", color=(0, 0, 0), align=1)
        if remaining >= 0:
            return size
        size -= 0.5
    return None


def export_pdf(pdf, figures, output_dir, event=None, progress=None):
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    pdf = Path(pdf)
    mono_path = directory / f"{pdf.stem}-figures-zh.pdf"
    dual_path = directory / f"{pdf.stem}-figures-dual.pdf"
    if pdf.resolve() in {mono_path.resolve(), dual_path.resolve()}:
        raise ValueError("输出不能覆盖原 PDF。")
    report = []
    with fitz.open(pdf) as original, fitz.open(pdf) as translated:
        page_ids = sorted({f.page - 1 for f in figures})
        for step, index in enumerate(page_ids):
            check_cancel(event)
            if progress:
                progress(step / max(1, len(page_ids)), f"回填第 {index + 1} 页")
            source, target = original[index], translated[index]
            rotation = source.rotation
            source.set_rotation(0)
            target.set_rotation(0)
            try:
                with fitz.open() as overlay_doc:
                    overlay = overlay_doc.new_page(width=source.rect.width, height=source.rect.height)
                    operations = []
                    for figure in [f for f in figures if f.page == index + 1]:
                        for label in figure.labels:
                            item = {"id": label.id, "page": figure.page, "source": label.text, "translation": label.translation,
                                    "bbox": label.bbox, "kind": label.source, "status": "skipped", "reason": label.reason}
                            report.append(item)
                            if not label.enabled or not label.translation.strip() or label.translation.strip() == label.text.strip():
                                item["reason"] = item["reason"] or "未选中、没有译文或译文等同原文"
                                continue
                            repair = None
                            if label.source == "raster":
                                repair, reason = clean_raster_label(source, label.bbox)
                                if repair is None:
                                    item["reason"] = reason
                                    continue
                            fitted = prepare_text(overlay, label, figure.bbox)
                            if fitted is None:
                                item["reason"] = "译文无法在原标签范围内排版"
                                continue
                            operations.append((label, repair))
                            item.update(status="replaced", reason="", font_size=round(fitted, 2))
                    # All translations and layouts have succeeded before deletion.
                    for label, repair in operations:
                        if label.source == "native":
                            target.add_redact_annot(fitz.Rect(label.bbox), fill=False)
                    if any(l.source == "native" for l, _ in operations):
                        target.apply_redactions(images=0, graphics=0, text=0)
                    for _, repair in operations:
                        if repair is not None:
                            stream, rect = repair
                            target.insert_image(rect, stream=stream, overlay=True)
                    if operations:
                        target.show_pdf_page(target.rect, overlay_doc, 0, overlay=True)
            finally:
                source.set_rotation(rotation)
                target.set_rotation(rotation)
        check_cancel(event)
        mono_part = mono_path.with_suffix(".part.pdf")
        translated.subset_fonts()
        translated.save(mono_part, garbage=4, deflate=True)
        with fitz.open() as dual:
            for index in range(len(original)):
                check_cancel(event)
                dual.insert_pdf(original, from_page=index, to_page=index)
                dual.insert_pdf(translated, from_page=index, to_page=index)
            dual_part = dual_path.with_suffix(".part.pdf")
            dual.save(dual_part, garbage=4, deflate=True)
        check_cancel(event)
        mono_part.replace(mono_path)
        dual_part.replace(dual_path)
    report_path = directory / "report.json"
    report_path.write_text(json.dumps({"figures": manifest(figures), "labels": report}, ensure_ascii=False, indent=2), encoding="utf-8")
    replaced = sum(i["status"] == "replaced" for i in report)
    return str(mono_path), str(dual_path), str(report_path), replaced
