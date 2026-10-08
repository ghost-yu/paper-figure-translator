"""Conservative figure-label replacement, keeping all other PDF content."""
from __future__ import annotations

import io
import json
from pathlib import Path

import cv2
import numpy as np
import pymupdf as fitz
from PIL import Image, ImageFont, ImageDraw
from functools import lru_cache
import os
import threading

from .core import check_cancel, crop, manifest, pix_array
from .vendor.comic_mask import detect_content_mask_in_bbox
from .vendor.comic_render import pil_word_wrap
from .vendor.comic_migan import inpaint_pipeline

MODEL_LOCK = threading.Lock()


@lru_cache(maxsize=1)
def repair_session():
    model = Path(os.environ.get("PAPER_FIGURES_MIGAN", str(Path(__file__).resolve().parents[1] / "workspace/models/migan_pipeline_v2.onnx")))
    if not model.exists():
        return None
    import onnxruntime as ort
    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    return ort.InferenceSession(str(model), options, providers=["CPUExecutionProvider"])


def chinese_font(size):
    # Use installed fonts without redistributing Microsoft font files.
    for path in [os.environ.get("PAPER_FIGURES_FONT", ""), "C:/Windows/Fonts/msyh.ttc", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"]:
        if path and Path(path).exists():
            return ImageFont.truetype(path, size=size), path
    buffer = fitz.Font("china-s").buffer
    return ImageFont.truetype(io.BytesIO(buffer), size=size), io.BytesIO(buffer)


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
    flat_background = np.mean(distances < 25) >= 0.75
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
    # Comic Translate's component mask retains glyph contours and punctuation.
    mask = detect_content_mask_in_bbox(image, min_area=2, margin=1)
    if not mask.any():
        return None, "漫画文字掩膜未找到完整字形"
    mask = cv2.dilate(mask, np.ones((3, 3), np.uint8))
    session = repair_session() if not flat_background else None
    if flat_background:
        # A learned inpainter can reconstruct letters instead of erasing them.
        # On uniform panels, fill the comic glyph mask with the sampled color.
        image[mask > 0] = background.astype(np.uint8)
    elif session is not None:
        # The original comic pipeline accepts uint8 RGB and an inverted mask.
        padded = np.pad(image, ((0, max(0, 512-h)), (0, max(0, 512-w)), (0, 0)), mode="edge")
        padded_mask = np.pad(mask, ((0, max(0, 512-h)), (0, max(0, 512-w))))
        with MODEL_LOCK:
            repaired = inpaint_pipeline(session, padded, padded_mask)[:h, :w]
        image[mask > 0] = repaired[mask > 0]
    else:
        return None, "背景复杂且未安装 MI-GAN，保留原文"
    stream = io.BytesIO()
    Image.fromarray(image).save(stream, format="PNG")
    actual_rect = fitz.Rect(pix.x / (dpi / 72), pix.y / (dpi / 72),
                            (pix.x + pix.width) / (dpi / 72), (pix.y + pix.height) / (dpi / 72))
    return (stream.getvalue(), actual_rect), ""


def prepare_text(overlay, label, figure_box, neighbors, source=None, repair=None):
    box = fitz.Rect(label.bbox) & fitz.Rect(figure_box)
    # A little available line spacing is needed for CJK font metrics. Bound
    # expansion by neighboring labels, not by arbitrary unlimited wrapping.
    up = min(1.5, box.y0 - figure_box[1])
    down = min(1.5, figure_box[3] - box.y1)
    for neighbor in neighbors:
        if neighbor.id == label.id:
            continue
        other = fitz.Rect(neighbor.bbox)
        if min(box.x1, other.x1) <= max(box.x0, other.x0):
            continue
        if other.y1 <= box.y0:
            up = min(up, max(0, (box.y0 - other.y1) / 2 - 0.1))
        if other.y0 >= box.y1:
            down = min(down, max(0, (other.y0 - box.y1) / 2 - 0.1))
    box.y0 -= up
    box.y1 += down
    # OCR bounds hug the English glyphs. Allow a small amount of adjacent
    # whitespace before shrinking Chinese into unreadably tiny text.
    left = min(6, box.width * 0.25, box.x0 - figure_box[0])
    right = min(6, box.width * 0.25, figure_box[2] - box.x1)
    for neighbor in neighbors:
        if neighbor.id == label.id:
            continue
        other = fitz.Rect(neighbor.bbox)
        if min(box.y1, other.y1) <= max(box.y0, other.y0):
            continue
        if other.x1 <= box.x0:
            left = min(left, max(0, (box.x0 - other.x1) / 2 - 0.1))
        if other.x0 >= box.x1:
            right = min(right, max(0, (other.x0 - box.x1) / 2 - 0.1))
    box.x0 -= left
    box.x1 += right
    scale = 300 / 72
    width, height = max(1, round(box.width * scale)), max(1, round(box.height * scale))
    if source is not None:
        pix = crop(source, box, 300)
        box = fitz.Rect(pix.x / scale, pix.y / scale, (pix.x+pix.width)/scale, (pix.y+pix.height)/scale)
        canvas = Image.fromarray(pix_array(pix))
        width, height = canvas.size
        if repair is not None:
            stream, repaired_box = repair
            cleaned = Image.open(io.BytesIO(stream)).convert("RGB")
            canvas.paste(cleaned, (round((repaired_box.x0-box.x0)*scale), round((repaired_box.y0-box.y0)*scale)))
    else:
        canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    initial = max(12, round(min(14, label.size, box.height * 0.85) * scale))
    _, path = chinese_font(initial)
    text, size = pil_word_wrap(canvas, (0, 0), path, label.translation,
                               width, height, "center", 2, initial, min_font_size=12)
    font, _ = chinese_font(size)
    draw = ImageDraw.Draw(canvas)
    bounds = draw.multiline_textbbox((0, 0), text, font=font, align="center", spacing=2)
    tw, th = bounds[2] - bounds[0], bounds[3] - bounds[1]
    if tw > width or th > height:
        return None
    draw.multiline_text(((width-tw)/2-bounds[0], (height-th)/2-bounds[1]), text,
                        font=font, fill=(0, 0, 0, 255), align="center", spacing=2)
    stream = io.BytesIO()
    canvas.save(stream, format="PNG")
    overlay.insert_image(box, stream=stream.getvalue())
    if source is not None and repair is None:
        # Later overlapping line patches must see earlier Chinese, not restore
        # the source English from the original background.
        source.insert_image(box, stream=stream.getvalue())
    # Keep translated labels searchable; visible glyphs use real font metrics.
    overlay.insert_text((box.x0, box.y1), label.translation, fontsize=3, fontname="china-s", render_mode=3)
    return size / scale


def export_pdf(pdf, figures, output_dir, event=None, progress=None, preserve_page_content=True):
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
                            if preserve_page_content or label.source in {"raster", "native-ocr"}:
                                repair, reason = clean_raster_label(source, label.bbox)
                                if repair is None:
                                    item["reason"] = reason
                                    continue
                            fitted = prepare_text(overlay, label, figure.bbox, figure.labels,
                                                  source if preserve_page_content else None, repair)
                            if fitted is None:
                                item["reason"] = "译文无法在原标签范围内排版"
                                continue
                            operations.append((label, repair))
                            item.update(status="replaced", reason="", font_size=round(fitted, 2))
                    if preserve_page_content and operations:
                        # Compose on one clean background. Independently cropped
                        # adjacent line patches can otherwise restore old glyphs.
                        overlay = overlay_doc.new_page(width=source.rect.width, height=source.rect.height)
                        with fitz.open() as background_doc:
                            background_doc.insert_pdf(original, from_page=index, to_page=index)
                            background = background_doc[0]
                            for _, repair in operations:
                                stream, rect = repair
                                background.insert_image(rect, stream=stream)
                            for label, _ in operations:
                                figure = next(f for f in figures if f.page == index+1 and any(l is label for l in f.labels))
                                prepare_text(overlay, label, figure.bbox, figure.labels, source=background)
                    # All translations and layouts have succeeded before deletion.
                    for label, repair in operations:
                        if not preserve_page_content and label.source in {"native", "native-ocr"}:
                            target.add_redact_annot(fitz.Rect(label.bbox), fill=False)
                    if not preserve_page_content and any(l.source in {"native", "native-ocr"} for l, _ in operations):
                        target.apply_redactions(images=0, graphics=0, text=0)
                    for _, repair in operations:
                        if repair is not None:
                            stream, rect = repair
                            target.insert_image(rect, stream=stream, overlay=True)
                    if operations:
                        target.show_pdf_page(target.rect, overlay_doc, overlay.number, overlay=True)
            finally:
                source.set_rotation(rotation)
                target.set_rotation(rotation)
        check_cancel(event)
        mono_part = mono_path.with_suffix(".part.pdf")
        if not preserve_page_content:
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
