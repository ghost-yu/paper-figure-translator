"""Adapted from ogkalu2/comic-translate, Apache-2.0.
Upstream commit: 8977b91a4f7a40c3917c5a268e9e7d78e1d818da
See THIRD_PARTY_NOTICES.md and licenses/comic-translate-Apache-2.0.txt.
Changes: use existing OpenCV instead of imkit/mahotas; use PIL font metrics
instead of Qt; only horizontal Chinese figure labels are exposed.
"""
from typing import Tuple, List
from PIL import Image, ImageFont, ImageDraw

def _wrap_no_space_text_greedily(text: str, measure_side, max_side: float) -> str:
    """Greedy wrapping for languages that do not rely on spaces between words."""

    paragraphs = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    wrapped_paragraphs: List[str] = []

    for paragraph in paragraphs:
        chars = [char for char in paragraph if char != " "]
        if not chars:
            wrapped_paragraphs.append("")
            continue

        lines: List[str] = []
        line = ""

        for char in chars:
            candidate = f"{line}{char}"
            if not line or measure_side(candidate) <= max_side:
                line = candidate
                continue

            lines.append(line)
            line = char

        if line:
            lines.append(line)

        wrapped_paragraphs.append("\n".join(lines))

    return "\n".join(wrapped_paragraphs)

def pil_word_wrap(image: Image, tbbox_top_left: Tuple, font_pth: str, text: str,
                  roi_width, roi_height, align: str, spacing, init_font_size: int, min_font_size: int = 10):
    """Break long text to multiple lines, and reduce point size
    until all text fits within a bounding box."""
    mutable_message = text
    font_size = init_font_size
    font = ImageFont.truetype(font_pth, font_size)

    def eval_metrics(txt, font):
        """Quick helper function to calculate width/height of text."""
        (left, top, right, bottom) = ImageDraw.Draw(image).multiline_textbbox(xy=tbbox_top_left, text=txt, font=font, align=align, spacing=spacing)
        return (right-left, bottom-top)

    while font_size > min_font_size:
        font = font.font_variant(size=font_size)
        width, height = eval_metrics(mutable_message, font)
        if height > roi_height:
            font_size -= 0.75  # Reduce pointsize
            mutable_message = text  # Restore original text
        elif width > roi_width:
            columns = len(mutable_message)
            while columns > 0:
                columns -= 1
                if columns == 0:
                    break
                mutable_message = _wrap_no_space_text_greedily(text, lambda candidate: eval_metrics(candidate, font)[0], roi_width)
                wrapped_width, _ = eval_metrics(mutable_message, font)
                if wrapped_width <= roi_width:
                    break
            if columns < 1:
                font_size -= 0.75  # Reduce pointsize
                mutable_message = text  # Restore original text
        else:
            break

    if font_size <= min_font_size:
        font_size = min_font_size
        mutable_message = text
        font = font.font_variant(size=font_size)

        # Wrap text to fit within as much as possible
        # Minimize cost function: (width - roi_width)^2 + (height - roi_height)^2
        # This is a brute force approach, but it works well enough
        min_cost = 1e9
        min_text = text
        for columns in range(1, len(text)):
            wrapped_text = _wrap_no_space_text_greedily(text, lambda candidate: eval_metrics(candidate, font)[0], roi_width)
            wrapped_width, wrapped_height = eval_metrics(wrapped_text, font)
            cost = (wrapped_width - roi_width)**2 + (wrapped_height - roi_height)**2
            if cost < min_cost:
                min_cost = cost
                min_text = wrapped_text

        mutable_message = min_text

    return mutable_message, font_size
