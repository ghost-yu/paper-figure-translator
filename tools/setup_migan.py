"""Download an optional, pinned 26.78 MiB CPU repair model; never an LLM."""
import hashlib
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
REVISION = "406830d0fa60666da0071c342ad2fbc8f30c5c64"
BASE = f"https://huggingface.co/andraniksargsyan/migan/resolve/{REVISION}/"
EXPECTED = "6f1f3530a1a2324b19752018ce756088b07973cda8d7d890034ace5c8a48c40b"


def main():
    directory = ROOT / "workspace/models"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "migan_pipeline_v2.onnx"
    if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == EXPECTED:
        print("MI-GAN is already installed and verified.")
        return
    partial = target.with_suffix(".part")
    digest = hashlib.sha256()
    try:
        with requests.get(BASE + target.name, stream=True, timeout=(15, 60)) as response:
            response.raise_for_status()
            with partial.open("wb") as output:
                for chunk in response.iter_content(1024 * 1024):
                    output.write(chunk)
                    digest.update(chunk)
        if digest.hexdigest() != EXPECTED:
            raise ValueError("Model checksum mismatch; download not installed.")
        response = requests.get(BASE + "LICENSE", timeout=(15, 30))
        response.raise_for_status()
        (directory / "MI-GAN-LICENSE.txt").write_text(response.text, encoding="utf-8")
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)
    print("MI-GAN installed locally. Restart the application to use it.")


if __name__ == "__main__":
    main()
