"""Integration tests use real CPU OCR on a mixed native/raster PDF figure."""
import hashlib
import io
from pathlib import Path
import tempfile
import threading
import unittest

import numpy as np
from PIL import Image, ImageDraw, ImageFont
import pymupdf as fitz

from paper_figures.api import APIConfig, Translator, protect, restore, validate_batch
from paper_figures.core import Scanner, Label, Figure, Cancelled, pages_from_text, translatable, readable_native, pix_array, crop
from paper_figures.render import export_pdf, clean_raster_label


def make_fixture(path):
    image = Image.new("RGB", (1000, 280), "white")
    draw = ImageDraw.Draw(image)
    font_path = Path("C:/Windows/Fonts/arial.ttf")
    font = ImageFont.truetype(str(font_path), 40) if font_path.exists() else ImageFont.load_default(size=40)
    draw.rounded_rectangle((40, 50, 350, 230), radius=12, fill="#e7f3ff", outline="#2470b0", width=4)
    draw.rounded_rectangle((650, 50, 960, 230), radius=12, fill="#edf8ec", outline="#36844a", width=4)
    draw.text((135, 112), "Input", font=font, fill="black")
    draw.text((740, 112), "Output", font=font, fill="black")
    draw.line((350, 140, 635, 140), fill="#2470b0", width=5)
    draw.polygon([(630, 130), (650, 140), (630, 150)], fill="#2470b0")
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    with fitz.open() as doc:
        page = doc.new_page(width=600, height=400)
        page.insert_text((40, 45), "Scientific paper body remains selectable.", fontsize=12)
        page.insert_image(fitz.Rect(50, 100, 550, 240), stream=stream.getvalue())
        page.draw_rect(fitz.Rect(150, 255, 330, 292), color=(0.2, 0.4, 0.6))
        page.insert_text((170, 280), "Feature Extraction", fontsize=13)
        page.insert_text((380, 280), "x_i", fontsize=12)
        page.insert_text((480, 280), "CNN", fontsize=12)
        page.insert_text((40, 355), "Figure 1. An example architecture.", fontsize=11)
        second = doc.new_page(width=600, height=400)
        second.insert_text((40, 45), "An unselected page.", fontsize=12)
        doc.save(path)


class Contracts(unittest.TestCase):
    def test_page_selection_and_protection(self):
        self.assertEqual(pages_from_text("1-2,2,4", 4), [0, 1, 3])
        with self.assertRaises(ValueError):
            pages_from_text("0", 4)
        for text in ["CNN", "ViT", "vit", "VIT", "x_i", "42", "p(y|x)=1"]:
            self.assertFalse(translatable(text))
        self.assertTrue(translatable("INPUT"))
        self.assertFalse(readable_native("\ufffddataset"))
        self.assertFalse(readable_native("\x1bnoise"))
        self.assertNotIn("test-secret", repr(APIConfig("https://example.invalid/v1", "test", "test-secret")))

    def test_api_invalid_batch_never_accepted(self):
        with self.assertRaises(ValueError):
            validate_batch('{"translations":[{"id":"a","text":"甲"},{"id":"a","text":"乙"}]}', {"a", "b"})
        with self.assertRaises(ValueError):
            validate_batch('{"translations":[{"id":"a","text":"甲"}]}', {"a", "b"})
        with self.assertRaises(ValueError):
            restore("忘记保留数字", ["1"])
        self.assertEqual(restore("第 __KEEP_0__ 层", ["1"]), "第 1 层")

    def test_context_cache_and_case_insensitive_abbreviations(self):
        text, values = protect("vit Layer 1", {"ViT"})
        self.assertEqual(values, ["vit", "1"])
        self.assertEqual(restore(text, values), "vit Layer 1")
        with tempfile.TemporaryDirectory() as directory:
            translator = Translator(APIConfig("https://example.invalid/v1", "test", "test-secret"), Path(directory) / "cache.json")
            self.assertNotEqual(translator.cache_key("expert", "robot control"), translator.cache_key("expert", "medical diagnosis"))

    def test_cancelled_export_does_not_write(self):
        with tempfile.TemporaryDirectory() as directory:
            pdf = Path(directory) / "source.pdf"
            make_fixture(pdf)
            event = threading.Event()
            event.set()
            with self.assertRaises(Cancelled):
                export_pdf(pdf, [], Path(directory) / "out", event)
            self.assertFalse((Path(directory) / "out/source-figures-zh.pdf").exists())


class MixedPDF(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = Path(__file__).resolve().parents[1] / "workspace/review"
        cls.directory.mkdir(parents=True, exist_ok=True)
        cls.pdf = cls.directory / "mixed-paper.pdf"
        make_fixture(cls.pdf)
        cls.original_hash = hashlib.sha256(cls.pdf.read_bytes()).hexdigest()
        cls.figures = Scanner().scan(cls.pdf, cls.directory / "previews", "1", [{"page": 1, "bbox": [45, 95, 555, 305]}])
        translations = {"Input": "输入", "Output": "输出", "Feature Extraction": "特征提取"}
        for figure in cls.figures:
            for label in figure.labels:
                label.translation = translations.get(label.text, "")
        cls.mono, cls.dual, cls.report, cls.replaced = export_pdf(cls.pdf, cls.figures, cls.directory)

    def test_real_ocr_and_native_mixed(self):
        labels = {l.text: l for f in self.figures for l in f.labels}
        self.assertIn("Input", labels)
        self.assertIn("Output", labels)
        self.assertEqual(labels["Input"].source, "raster")
        self.assertEqual(labels["Feature Extraction"].source, "native")
        self.assertFalse(labels["CNN"].enabled)
        self.assertFalse(labels["x_i"].enabled)
        self.assertEqual(len([l for l in labels.values() if l.text == "Feature Extraction"]), 1)

    def test_export_preserves_original_and_unselected_pages(self):
        self.assertEqual(hashlib.sha256(self.pdf.read_bytes()).hexdigest(), self.original_hash)
        self.assertEqual(self.replaced, 3)
        with fitz.open(self.pdf) as source, fitz.open(self.mono) as translated, fitz.open(self.dual) as dual:
            self.assertEqual(len(translated), 2)
            self.assertEqual(len(dual), 4)
            self.assertEqual(source[1].get_pixmap().samples, translated[1].get_pixmap().samples)
            self.assertEqual(source[0].get_pixmap().samples, dual[0].get_pixmap().samples)
            self.assertIn("Scientific paper body remains selectable.", translated[0].get_text())
            self.assertIn("CNN", translated[0].get_text())
            self.assertIn("x_i", translated[0].get_text())
            self.assertNotIn("Feature Extraction", translated[0].get_text())
            self.assertIn("特征提取", translated[0].get_text())
            a, b = pix_array(source[0].get_pixmap()), pix_array(translated[0].get_pixmap())
            # Arrow is between modules, outside all label repair rectangles.
            self.assertTrue(np.array_equal(a[150:190, 230:370], b[150:190, 230:370]))
            source[0].get_pixmap(matrix=fitz.Matrix(1.5, 1.5)).save(self.directory / "before.png")
            translated[0].get_pixmap(matrix=fitz.Matrix(1.5, 1.5)).save(self.directory / "after.png")

    def test_background_and_line_collision_is_conservative(self):
        with fitz.open(self.pdf) as doc:
            repair, reason = clean_raster_label(doc[0], [220, 167, 377, 174])
            self.assertIsNone(repair)
            self.assertTrue(reason)

    def test_rotated_cropped_page_coordinate_mapping(self):
        pdf = self.directory / "rotated-cropped.pdf"
        with fitz.open(self.pdf) as doc:
            doc[0].set_cropbox(fitz.Rect(30, 50, 560, 380))
            doc[0].set_rotation(90)
            doc.save(pdf)
        figures = Scanner().scan(pdf, self.directory / "rotated-previews", "1", [{"page": 1, "bbox": [15, 45, 525, 255]}])
        replacements = {"Input": "输入", "Output": "输出", "Feature Extraction": "特征提取"}
        for figure in figures:
            for label in figure.labels:
                label.translation = replacements.get(label.text, "")
        mono, dual, _, replaced = export_pdf(pdf, figures, self.directory / "rotated-output")
        self.assertEqual(replaced, 3)
        with fitz.open(pdf) as source, fitz.open(mono) as translated, fitz.open(dual) as bilingual:
            self.assertEqual(translated[0].rotation, 90)
            self.assertEqual(translated[0].cropbox, source[0].cropbox)
            self.assertEqual(bilingual[0].get_pixmap().samples, source[0].get_pixmap().samples)
            self.assertIn("特征提取", translated[0].get_text())


if __name__ == "__main__":
    unittest.main()
