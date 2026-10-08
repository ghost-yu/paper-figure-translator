"""Reuse a nearby Windows pdf2zh runtime; never copy or modify its config."""
from pathlib import Path
import sys

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root))
bundled = root.parent / "build/site-packages"
if bundled.is_dir():
    sys.path.insert(1, str(bundled))

if __name__ == "__main__":
    from paper_figures.cli import main
    main()
