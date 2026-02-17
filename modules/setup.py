import os
import sys
import subprocess
import importlib
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

REQUIRED_PACKAGES = [
    "tidalapi", "deezer-python", "yt_dlp", "faster_whisper",
    "mutagen", "requests", "Pillow", "pyyaml", "beautifulsoup4", "musicbrainzngs"
]

def check_dependencies():
    """Check if all required packages are installed."""
    missing = []
    for package in REQUIRED_PACKAGES:
        try:
            importlib.import_module(package.replace("-", "_"))
        except ImportError:
            missing.append(package)
    return missing

def install_dependencies():
    """Install missing dependencies via pip."""
    missing = check_dependencies()
    if not missing:
        logger.info("All dependencies are installed.")
        return True

    logger.info(f"Installing missing dependencies: {', '.join(missing)}")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install"] + missing)
        logger.info("Dependencies installed successfully.")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to install dependencies: {e}")
        return False

def check_model(model_size="medium", model_dir="models"):
    """Check if faster-whisper model exists, else download it."""
    # faster-whisper handles downloading automatically if we pass a local path,
    # OR if we pass a model name, it downloads to cache.
    # To be explicit and "include the file", we can pre-download it.

    # However, faster-whisper's download_model is the best way.
    try:
        from faster_whisper import download_model

        model_path = Path(model_dir) / model_size
        if model_path.exists() and any(model_path.iterdir()):
            logger.info(f"Model '{model_size}' found at {model_path}")
            return str(model_path)

        logger.info(f"Downloading Whisper model '{model_size}' to {model_path}...")
        download_model(model_size, output_dir=str(model_path))
        logger.info("Model download complete.")
        return str(model_path)

    except ImportError:
        logger.error("faster_whisper not found. Cannot check/download model.")
        return None
    except Exception as e:
        logger.error(f"Model check/download failed: {e}")
        return None

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    install_dependencies()
    check_model()
