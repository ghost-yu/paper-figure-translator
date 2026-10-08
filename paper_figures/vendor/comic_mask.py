"""Adapted from ogkalu2/comic-translate, Apache-2.0.
Upstream commit: 8977b91a4f7a40c3917c5a268e9e7d78e1d818da
See THIRD_PARTY_NOTICES.md and licenses/comic-translate-Apache-2.0.txt.
Changes: use existing OpenCV instead of imkit/mahotas; use PIL font metrics
instead of Qt; only horizontal Chinese figure labels are exposed.
"""
import cv2
import numpy as np

def detect_content_mask_in_bbox(
    image: np.ndarray,
    min_area: int = 10,
    margin: int = 1,
) -> np.ndarray:
    """
    Detect text-like content as a binary component mask instead of box unions.
    """
    if image is None or image.size == 0:
        return np.zeros((0, 0), dtype=np.uint8)

    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    threshold = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[0]

    binary_black_text = (gray < threshold).astype(np.uint8)
    binary_white_text = (gray > threshold).astype(np.uint8)
    if not np.any(binary_black_text):
        binary_black_text = (gray == gray.min()).astype(np.uint8)
    if not np.any(binary_white_text):
        binary_white_text = (gray == gray.max()).astype(np.uint8)

    mask_black = _mask_from_component_stats(binary_black_text, min_area=min_area, margin=margin)
    mask_white = _mask_from_component_stats(binary_white_text, min_area=min_area, margin=margin)
    return np.where((mask_black > 0) | (mask_white > 0), 255, 0).astype(np.uint8)

def _mask_from_component_stats(
    binary_mask: np.ndarray,
    *,
    min_area: int,
    margin: int,
    small_component_min_area: int = 4,
    small_component_max_span: int = 6,
) -> np.ndarray:
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(binary_mask, connectivity=8)
    if num_labels <= 1:
        return np.zeros(binary_mask.shape[:2], dtype=np.uint8)

    stats_no_bg = stats[1:]
    if stats_no_bg.shape[0] == 0:
        return np.zeros(binary_mask.shape[:2], dtype=np.uint8)

    height, width = binary_mask.shape[:2]
    x1 = stats_no_bg[:, cv2.CC_STAT_LEFT]
    y1 = stats_no_bg[:, cv2.CC_STAT_TOP]
    w = stats_no_bg[:, cv2.CC_STAT_WIDTH]
    h = stats_no_bg[:, cv2.CC_STAT_HEIGHT]
    area = stats_no_bg[:, cv2.CC_STAT_AREA]

    area_mask = area > min_area
    small_component_mask = (
        (area >= small_component_min_area)
        & (w <= small_component_max_span)
        & (h <= small_component_max_span)
    )
    border_mask = (
        (x1 >= margin)
        & (y1 >= margin)
        & ((x1 + w) <= width - margin)
        & ((y1 + h) <= height - margin)
    )
    keep = (area_mask | small_component_mask) & border_mask

    # Filter out components that are too large (likely background fills in colored narration boxes)
    if height * width > 150:
        max_area = int(0.50 * height * width)
        keep = keep & (area < max_area)

    if not np.any(keep):
        return np.zeros(binary_mask.shape[:2], dtype=np.uint8)

    keep_labels = np.flatnonzero(keep) + 1
    return np.where(np.isin(labels, keep_labels), 255, 0).astype(np.uint8)
