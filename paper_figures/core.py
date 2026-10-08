"""PDF coordinates, figure discovery and mixed native/raster label extraction.

SPDX-License-Identifier: AGPL-3.0-only
Implementation written for this project; no upstream implementation copied.
"""
from __future__ import annotations

import ast
from dataclasses import asdict, dataclass, field
from pathlib import Path
import threading
import re
from difflib import SequenceMatcher

import cv2
import numpy as np
import pymupdf as fitz

class Cancelled(RuntimeError):
    pass


def check_cancel(event):
    if event is not None and event.is_set():
        raise Cancelled("任务已取消，原文件未修改。")


@dataclass
class Label:
    id: str
    text: str
    bbox: list[float]
    source: str
    confidence: float = 1.0
    size: float = 10.0
    enabled: bool = True
    translation: str = ""
    reason: str = ""


@dataclass
class Figure:
    id: str
    page: int
    bbox: list[float]
    method: str
    preview: str
    labels: list[Label] = field(default_factory=list)
    caption: str = ""
    context: str = ""


def pages_from_text(value: str, count: int) -> list[int]:
    if not value.strip():
        return list(range(count))
    pages = set()
    for term in value.replace("，", ",").split(","):
        parts = term.strip().split("-")
        if len(parts) == 1:
            start = end = int(parts[0])
        elif len(parts) == 2:
            start, end = int(parts[0]), int(parts[1])
        else:
            raise ValueError("页码示例：1-3,5")
        if not 1 <= start <= end <= count:
            raise ValueError(f"页码必须在 1 到 {count} 之间。")
        pages.update(range(start - 1, end))
    return sorted(pages)


def translatable(text: str) -> bool:
    text = text.strip()
    # Only a language-candidate check. Terminology and abbreviation decisions
    # belong to the contextual API, not a local word list or formula regex.
    return bool(re.search(r"[A-Za-z]{2,}", text))


def readable_native(text):
    return "\ufffd" not in text and not any(ord(c) < 32 and c not in "\n\t\r" for c in text)


def figure_context(page, figure_box):
    """Bounded nearby prose and closest caption, excluding figure labels."""
    rect = fitz.Rect(figure_box)
    candidates = []
    captions = []
    for block in page.get_text("dict", flags=fitz.TEXTFLAGS_TEXT)["blocks"]:
        box = fitz.Rect(block["bbox"])
        if overlap_fraction(box, rect) > 0.15:
            continue
        text = " ".join("".join(span["text"] for span in line["spans"]) for line in block.get("lines", []))
        if not readable_native(text) or len(text.strip()) < 20:
            continue
        distance = max(0, rect.y0 - box.y1, box.y0 - rect.y1)
        if re.match(r"\s*(?:fig(?:ure)?\.?\s*\d|图\s*\d)", text, re.I):
            captions.append((distance, text))
        elif distance < 240:
            candidates.append((distance, box.y0, text))
    caption = min(captions, default=(0, ""), key=lambda x: x[0])[1][:1000]
    nearest = sorted(candidates)[:2]
    context = "\n\n".join(item[2][:900] for item in sorted(nearest, key=lambda x: x[1]))[:1800]
    return caption, context


def pix_array(pix) -> np.ndarray:
    return np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 3).copy()


def crop(page, bbox, dpi=240):
    return page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), clip=fitz.Rect(bbox), colorspace=fitz.csRGB, alpha=False, annots=False)


def pixel_box_to_pdf(box, pix, dpi):
    """pix.x/y include crop rounding; page coordinates are unrotated."""
    scale = dpi / 72
    xs, ys = zip(*box)
    return [(min(xs) + pix.x) / scale, (min(ys) + pix.y) / scale,
            (max(xs) + pix.x) / scale, (max(ys) + pix.y) / scale]


def overlap_fraction(a, b):
    a, b = fitz.Rect(a), fitz.Rect(b)
    area = min(a.get_area(), b.get_area())
    return (a & b).get_area() / area if area > 0 else 0.0


class FigureDetector:
    """Optional existing DocLayout YOLO model; never downloads weights."""
    def __init__(self, model_path=None):
        self.path = Path(model_path) if model_path else Path.home() / ".cache/babeldoc/models/doclayout_yolo_docstructbench_imgsz1024.onnx"
        self.session = None

    def detect(self, page):
        if not self.path.is_file():
            # Embedded-image fallback misses diagrams built entirely from vectors.
            return [(fitz.Rect(i["bbox"]), "embedded-image") for i in page.get_image_info()
                    if fitz.Rect(i["bbox"]).get_area() > 900
                    and fitz.Rect(i["bbox"]).get_area() < page.rect.get_area() * 0.85]
        if self.session is None:
            import onnxruntime as ort
            options = ort.SessionOptions()
            options.intra_op_num_threads = 2
            self.session = ort.InferenceSession(str(self.path), sess_options=options, providers=["CPUExecutionProvider"])
        metadata = self.session.get_modelmeta().custom_metadata_map
        names = ast.literal_eval(metadata["names"])
        pix = page.get_pixmap(colorspace=fitz.csRGB, alpha=False, annots=False)
        image = pix_array(pix)[:, :, ::-1]
        h, w = image.shape[:2]
        gain = min(1024 / h, 1024 / w)
        nw, nh = round(w * gain), round(h * gain)
        resized = cv2.resize(image, (nw, nh))
        # The existing model uses stride-aligned minimal padding.
        pw, ph = (1024 - nw) % 32, (1024 - nh) % 32
        left, top = round(pw / 2 - 0.1), round(ph / 2 - 0.1)
        tensor = cv2.copyMakeBorder(resized, top, ph - top, left, pw - left, cv2.BORDER_CONSTANT, value=(114, 114, 114))
        tensor = tensor.transpose(2, 0, 1)[None].astype(np.float32) / 255
        pred = self.session.run(None, {self.session.get_inputs()[0].name: tensor})[0]
        regions = []
        for row in pred.reshape(-1, pred.shape[-1]):
            if row[-2] < 0.4 or names[int(row[-1])] != "figure":
                continue
            x0, y0, x1, y1 = (row[:4] - [left, top, left, top]) / gain
            rect = fitz.Rect(x0 * page.rect.width / w, y0 * page.rect.height / h,
                             x1 * page.rect.width / w, y1 * page.rect.height / h) & page.rect
            if not rect.is_empty and rect.get_area() > 900:
                regions.append((rect, "layout"))
        return regions


class Scanner:
    def __init__(self, model_path=None, dpi=240):
        self.detector = FigureDetector(model_path)
        self.dpi = dpi
        self.ocr = None
        self.lock = threading.Lock()

    def recognize(self, pix):
        # ONNX sessions are reused, bounded CPU threads keep the UI responsive.
        with self.lock:
            if self.ocr is None:
                from rapidocr_onnxruntime import RapidOCR
                self.ocr = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=2)
            result, _ = self.ocr(pix_array(pix))
        return result or []

    def scan(self, pdf, workdir, pages="", manual=None, event=None, progress=None):
        directory = Path(workdir)
        directory.mkdir(parents=True, exist_ok=True)
        figures = []
        with fitz.open(pdf) as doc:
            if doc.needs_pass:
                raise ValueError("请先解密 PDF，再导入。")
            selected = pages_from_text(pages, len(doc))
            for step, index in enumerate(selected):
                check_cancel(event)
                page = doc[index]
                page.set_rotation(0)
                if progress:
                    progress(step / len(selected), f"识别第 {index + 1} 页图表")
                if manual is not None:
                    regions = [(fitz.Rect(r["bbox"]) & page.rect, "manual") for r in manual if int(r["page"]) == index + 1]
                else:
                    regions = self.detector.detect(page)
                accepted = []
                for rect, method in regions:
                    if rect.is_empty or rect.width < 8 or rect.height < 8:
                        continue
                    if any(overlap_fraction(rect, old) > 0.85 for old in accepted):
                        continue
                    accepted.append(rect)
                    number = len(accepted)
                    ident = f"p{index + 1}f{number}"
                    pix = crop(page, rect, self.dpi)
                    preview = str(directory / f"{ident}.png")
                    pix.save(preview)
                    figure = Figure(ident, index + 1, list(rect), method, preview)
                    figure.caption, figure.context = figure_context(page, rect)
                    traces = page.get_texttrace()
                    native = []
                    unreadable = []
                    for block in page.get_text("dict", flags=fitz.TEXTFLAGS_TEXT)["blocks"]:
                        for line in block.get("lines", []):
                            for span in line["spans"]:
                                bbox = fitz.Rect(span["bbox"])
                                if not rect.contains(bbox.tl + (bbox.br - bbox.tl) / 2) or not span["text"].strip():
                                    continue
                                if any((t.get("type") == 3 or t.get("opacity", 1) == 0)
                                       and overlap_fraction(bbox, t["bbox"]) > 0.8 for t in traces):
                                    continue
                                if not readable_native(span["text"]):
                                    unreadable.append(list(bbox))
                                    continue
                                direction = line.get("dir", (1, 0))
                                reason = "旋转标签待人工处理" if abs(direction[1]) > 0.15 or direction[0] < 0 else ""
                                native.append(Label("", span["text"].strip(), list(bbox), "native", size=span["size"],
                                                    enabled=not reason and translatable(span["text"]), reason=reason))
                    figure.labels.extend(native)
                    check_cancel(event)
                    # OCR must run even if this figure already has some native text.
                    for box, text, confidence in self.recognize(pix):
                        bbox = pixel_box_to_pdf(box, pix, self.dpi)
                        matching = [n for n in native if overlap_fraction(bbox, n.bbox) > 0.45]
                        if matching:
                            # Bad font mappings can also produce plausible Latin
                            # garbage. High-confidence OCR verifies a whole span.
                            if len(matching) == 1 and confidence >= 0.9:
                                n = matching[0]
                                normal = lambda s: re.sub(r"\s+", "", s).casefold()
                                if (fitz.Rect(bbox) & fitz.Rect(n.bbox)).get_area() / max(1, fitz.Rect(n.bbox).get_area()) > 0.75:
                                    if SequenceMatcher(None, normal(n.text), normal(text)).ratio() < 0.55:
                                        n.text = text
                                        n.source = "native-ocr"
                                        n.confidence = float(confidence)
                                        n.enabled = not n.reason and translatable(text)
                            continue
                        angled = (abs(box[1][1] - box[0][1]) > max(3, abs(box[1][0] - box[0][0]) * 0.15)
                                  or (bbox[3]-bbox[1] > 2*(bbox[2]-bbox[0]) and len(text) > 5))
                        reason = "识别置信度偏低" if confidence < 0.8 else ("旋转标签待人工处理" if angled else "")
                        kind = "native-ocr" if any(overlap_fraction(bbox, old) > 0.45 for old in unreadable) else "raster"
                        figure.labels.append(Label("", text, bbox, kind, float(confidence), (bbox[3] - bbox[1]) * 0.8,
                                                   not reason and translatable(text), reason=reason))
                    figure.labels.sort(key=lambda l: (l.bbox[1], l.bbox[0]))
                    for i, label in enumerate(figure.labels):
                        label.id = f"{ident}t{i + 1}"
                        if not translatable(label.text) and not label.reason:
                            label.reason = "非英文标签，默认跳过"
                    figures.append(figure)
        return figures


def manifest(figures):
    return [asdict(f) for f in figures]
