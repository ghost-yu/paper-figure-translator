"""Adapted from ogkalu2/comic-translate, Apache-2.0.
Upstream commit: 8977b91a4f7a40c3917c5a268e9e7d78e1d818da
See THIRD_PARTY_NOTICES.md and licenses/comic-translate-Apache-2.0.txt.
Changes: use existing OpenCV instead of imkit/mahotas; use PIL font metrics
instead of Qt; only horizontal Chinese figure labels are exposed.
"""
import numpy as np
import os

def inpaint_pipeline(session, image, mask):
    binary_mask = np.where(mask > 120, 0, 255).astype(np.uint8)  # Invert: 0=masked, 255=known

    # Inspect expected input shapes (may contain symbolic dims)
    inps = session.get_inputs()
    img_nchw = np.transpose(image, (2, 0, 1))[np.newaxis, ...]  # (1, 3, H, W) uint8
    # Ensure mask is 2D before adding batch/channel (pad utility may have added a trailing channel)
    if binary_mask.ndim == 3 and binary_mask.shape[2] == 1:
        binary_mask_2d = binary_mask[:, :, 0]
    else:
        binary_mask_2d = binary_mask
    mask_nchw = binary_mask_2d[np.newaxis, np.newaxis, ...]  # (1, 1, H, W)

    ort_inputs = {
        inps[0].name: img_nchw,
        inps[1].name: mask_nchw
    }
    # Optional quick shape debug (can be silenced later)
    if os.environ.get('MIGAN_DEBUG_SHAPES') == '1':
        print(f"[MIGAN ONNX] Feeding image shape {img_nchw.shape} mask shape {mask_nchw.shape} orig mask shape {mask.shape}")
    out = session.run(None, ort_inputs)[0]  # Should be (1, 3, H, W) uint8 RGB
    out_img = np.transpose(out[0], (1, 2, 0))  # Convert to (H, W, 3)
    cur_res = out_img  # Keep in RGB format
    return cur_res
