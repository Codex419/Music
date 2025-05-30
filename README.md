# Comprehensive Music and Video Processing Suite

This suite offers a collection of tools designed to manage and process music and video files. It includes functionalities for downloading music videos, transferring metadata between audio and video files, and generating transcriptions for audio and video content. The suite provides both graphical user interfaces (GUIs) for ease of use and a command-line interface (CLI) for automation and batch processing.

## Features

*   **Metadata Management:** Transfer metadata (artist, title, album, etc.) from audio files to corresponding MP4 video files (`Metadata.pyw`, `main_processor.py`).
*   **Music Video Downloading:** Search and download music videos from YouTube based on audio file metadata (`Music Video Downloader.pyw`, `main_processor.py`).
    *   Automatic and manual video selection modes.
    *   Configurable video/audio quality.
    *   Option to override existing video files.
*   **Audio/Video Transcription:** Generate text transcriptions (TXT, SRT, LRC) from audio and video files using various Whisper model sizes (`Transcribe Audio Video.pyw`, `main_processor.py`).
    *   Supports GPU (CUDA) and CPU processing.
    *   Adjustable parameters like beam size and VAD filter.
    *   Spectrogram visualization for audio content.
*   **Batch Processing:** Process multiple files in a directory, including subfolders, for all main functionalities (`Music Video Downloader.pyw`, `Transcribe Audio Video.pyw`, `main_processor.py`).
*   **Graphical User Interfaces:** Easy-to-use GUIs for metadata transfer, video downloading, and transcription tasks.
*   **Command-Line Interface:** A powerful CLI script (`main_processor.py`) for automated processing and integration into workflows.
*   **Configuration File:** `main_processor.py` supports a `config.json` for setting default paths and parameters.

## Scripts Overview

### `Metadata.pyw`

*   **Purpose:** A GUI application designed to transfer metadata from local audio files (like FLAC, MP3) to MP4 video files.
*   **Key Functionalities:**
    *   Browses for a directory of MP4 videos and a root directory for an audio library.
    *   Parses MP4 filenames (expected format: `Artist - Title.mp4`) to extract artist and title.
    *   Searches the audio library for a matching audio file based on its metadata (artist and title).
    *   If a match is found, it copies various metadata tags (artist, title, album, genre, year, track/disc number, compilation, composer, comment) from the audio file to the MP4 file.
    *   Provides a log area to display processing steps, successes, and errors.
    *   Uses `mutagen` for reading and writing metadata.

### `Music Video Downloader.pyw`

*   **Purpose:** A GUI application to find and download music videos from YouTube for audio files in a user's music library.
*   **Key Functionalities:**
    *   Scans a selected music folder for audio files.
    *   Extracts artist and title metadata from each audio file (using `mutagen` or filename parsing as a fallback).
    *   Searches YouTube (via `yt-dlp`) for music videos matching the artist and title.
    *   Provides an "Interactive Mode" to manually select from search results or provide a custom search query/URL if automatic selection fails.
    *   Offers a "No Trust Mode" to force manual selection for every file, bypassing automatic filtering.
    *   Supports configurable video/audio quality formats for `yt-dlp`.
    *   Allows setting a delay between downloads.
    *   Option to override (re-download) existing video files.
    *   Displays a list of files with their processing status (queued, downloading, complete, failed, etc.).
    *   Includes a log area for detailed messages.
    *   Dependencies: `mutagen`, `requests`, `Pillow` (for thumbnails), `yt-dlp` (external).

### `Transcribe Audio Video.pyw`

*   **Purpose:** A GUI application for transcribing audio and video files using the `faster-whisper` library.
*   **Key Functionalities:**
    *   Supports single file or batch directory processing (including subfolders).
    *   Allows selection of Whisper model size (tiny, base, small, medium, large-v1/v2/v3, and distilled versions).
    *   Option for model quantization (e.g., int8, float16) to optimize for CPU/memory.
    *   Device selection (CPU or CUDA GPU if available).
    *   Configurable compute type (e.g., float16, int8) for the selected device.
    *   Adjustable parameters: beam size, VAD (Voice Activity Detection) filter.
    *   Option to overwrite existing output transcription files.
    *   Displays a Mel spectrogram of the audio being processed.
    *   Shows a file queue with processing status and progress for each file.
    *   Outputs transcriptions in TXT format (always), SRT format (for videos), and LRC format (for audio files).
    *   Includes a menu to help install dependencies and open the model download folder.
    *   Dependencies: `librosa`, `numpy`, `matplotlib`, `tkinterdnd2-universal`, `faster-whisper`, `torch` (for GPU). `FFmpeg` (external) might be needed for certain audio/video formats.

### `main_processor.py`

*   **Purpose:** A command-line script that automates a full workflow: scanning a music library, finding/downloading corresponding music videos, transferring metadata, and transcribing both audio and video files.
*   **Key Functionalities:**
    *   Scans a specified music library directory for audio files.
    *   Extracts metadata (artist, title) from audio files.
    *   For each song:
        *   Searches YouTube (via `yt-dlp`) for a music video.
        *   Downloads the selected video to a structured output directory (`Output_Dir/Artist - Title/Artist - Title.ext`).
        *   Transfers metadata from the original audio file to the downloaded video file.
        *   Transcribes the downloaded video file.
        *   Transcribes the original audio file.
    *   Supports configuration through a `config.json` file (can be generated using `--generate_config`).
    *   Allows customization of `yt-dlp` path, video quality, search result count, and various transcription parameters (model size, device, compute type, VAD, beam size, language) via CLI arguments or the config file.
    *   Provides logging of its operations.
    *   Dependencies: `mutagen`, `faster-whisper`, `torch` (for GPU), `yt-dlp` (external).

## Dependencies

### Python Libraries

*   **Core GUI:**
    *   `tkinter`: Standard Python library for GUI. (Usually included with Python installations)
    *   `tkinterdnd2-universal`: For drag-and-drop functionality in `Transcribe Audio Video.pyw`.
*   **Metadata:**
    *   `mutagen`: For reading and writing audio metadata.
*   **Downloading & Web:**
    *   `requests`: For making HTTP requests (used by `Music Video Downloader.pyw` for thumbnails).
*   **Audio Processing & Transcription:**
    *   `faster-whisper`: For efficient audio transcription using Whisper models.
    *   `librosa`: For audio analysis and spectrogram generation in `Transcribe Audio Video.pyw`.
    *   `numpy`: Dependency for `librosa` and `matplotlib`.
    *   `torch`: Required for `faster-whisper`, especially for GPU support (CUDA).
*   **Imaging & Plotting:**
    *   `Pillow` (PIL): For image manipulation (thumbnails in `Music Video Downloader.pyw`).
    *   `matplotlib`: For plotting spectrograms in `Transcribe Audio Video.pyw`.

### External Tools

*   **`yt-dlp`**: A command-line program to download videos from YouTube and other sites.
    *   Required by: `Music Video Downloader.pyw`, `main_processor.py`.
    *   Installation: Must be installed separately and ideally added to your system's PATH, or its path specified in the config for `main_processor.py`.
*   **`FFmpeg`**: A multimedia framework.
    *   Often required by: `librosa` (and consequently `Transcribe Audio Video.pyw`) for loading various audio/video file formats.
    *   Installation: Should be installed separately and ideally added to your system's PATH.

## Usage

### GUI Applications

(`Metadata.pyw`, `Music Video Downloader.pyw`, `Transcribe Audio Video.pyw`)

1.  **Install Dependencies:** Ensure all Python libraries listed above are installed. You can typically install them using pip:
    ```bash
    pip install mutagen requests Pillow faster-whisper librosa numpy matplotlib tkinterdnd2-universal torch torchvision torchaudio
    ```
    (Note: `torch` installation might vary based on your system and CUDA requirements. Refer to the [PyTorch official website](https://pytorch.org/get-started/locally/) for specific instructions.)
2.  **Install External Tools:**
    *   Install `yt-dlp` from its [official repository](https://github.com/yt-dlp/yt-dlp).
    *   Install `FFmpeg` from its [official website](https://ffmpeg.org/download.html).
    *   Ensure both are added to your system's PATH or are otherwise accessible.
3.  **Run the Scripts:**
    Navigate to the directory containing the scripts and run them using Python:
    ```bash
    python Metadata.pyw
    python "Music Video Downloader.pyw"
    python "Transcribe Audio Video.pyw"
    ```
    (Note: The script names `Music Video Downloader.pyw` and `Transcribe Audio Video.pyw` do not actually contain spaces in the repository, so quotes may not be strictly necessary unless your local copies are renamed.)
4.  Follow the on-screen instructions and options within each application.
    *   `Transcribe Audio Video.pyw` includes a "Tools" menu that can help guide you through installing some core dependencies and checking PyTorch/CUDA status.

### Command-Line Interface (`main_processor.py`)

1.  **Install Dependencies:** Ensure all Python dependencies (especially `mutagen`, `faster-whisper`, `torch`) and external tools (`yt-dlp`) are installed and configured.
2.  `main_processor.py` is highly configurable via command-line arguments or a `config.json` file.
3.  **View Help:** To see all available command-line options:
    ```bash
    python main_processor.py --help
    ```
4.  **Example Usage:**
    ```bash
    python main_processor.py --music_library "/path/to/your/music" --output_dir "/path/to/your/output"
    ```
5.  **Key Command-Line Arguments:**
    *   `--music_library PATH`: Path to your music library. (Required)
    *   `--output_dir PATH`: Main directory where outputs will be saved. (Required)
    *   `--yt_dlp_path PATH`: Path to the `yt-dlp` executable (defaults to "yt-dlp").
    *   `--video_quality FORMAT_STRING`: `yt-dlp` video quality string.
    *   `--search_results NUM`: Number of YouTube search results to fetch.
    *   `--transcribe_model_size MODEL`: Whisper model size (e.g., "base", "small", "large-v2").
    *   `--transcribe_device DEVICE`: Device for transcription ("cuda" or "cpu").
    *   `--transcribe_compute_type TYPE`: Compute type for transcription (e.g., "float16", "int8").
    *   `--transcribe_vad`: Enable Voice Activity Detection (VAD) filter.
    *   `--transcribe_beam_size NUM`: Beam size for transcription.
    *   `--transcribe_language LANG_CODE`: Language code for transcription (e.g., "en", "es"; defaults to auto-detect).
    *   `--config_file PATH`: Path to a custom `config.json` file.
    *   `--generate_config [PATH]`: Generate a sample `config.json` file (defaults to `config.json` in script's directory) and exit.

## Configuration (`main_processor.py`)

The `main_processor.py` script can utilize a `config.json` file for default settings. Command-line arguments will override settings provided in the configuration file.

*   **Generating a Sample Configuration:**
    To create a sample `config.json` in the script's directory:
    ```bash
    python main_processor.py --generate_config
    ```
    To specify a custom path for the generated config:
    ```bash
    python main_processor.py --generate_config /path/to/your/custom_config.json
    ```
*   **Editing the Configuration:**
    Modify the generated JSON file to set your default paths (e.g., `music_library`, `output_dir`), `yt-dlp` settings, and transcription parameters.

## Troubleshooting & Notes

*   **`yt-dlp` Not Found:**
    *   Ensure `yt-dlp` is installed correctly and that its location is included in your system's PATH environment variable.
    *   For `main_processor.py`, you can explicitly provide the path to the `yt-dlp` executable using the `--yt_dlp_path` argument or by setting it in your `config.json`.
*   **`FFmpeg` Not Found:**
    *   The `Transcribe Audio Video.pyw` script (via the `librosa` library) may require `FFmpeg` to load and process certain audio or video file formats.
    *   Install `FFmpeg` from its official website and ensure its location is added to your system's PATH.
*   **GPU Support (CUDA for NVIDIA GPUs):**
    *   For GPU-accelerated transcription in `Transcribe Audio Video.pyw` and `main_processor.py`, an NVIDIA GPU compatible with CUDA is necessary.
    *   PyTorch must be installed with the correct CUDA toolkit version that matches your GPU drivers. The "Tools" menu in `Transcribe Audio Video.pyw` offers an option to check PyTorch/CUDA status and provides a link to the official PyTorch installation guide.
*   **Model Downloads:**
    *   `faster-whisper` models are downloaded automatically on their first use.
    *   `Transcribe Audio Video.pyw` saves models to an "Audio Models" subfolder within its directory.
    *   `main_processor.py` saves models to an "Audio_Models_main_processor" subfolder within its directory.
    *   You can pre-download models or change the download location if needed (consult `faster-whisper` documentation).
*   **File Permissions:**
    *   Ensure that the scripts have the necessary read permissions for input files/directories and write permissions for the specified output directories and model download locations.
*   **Paths with Spaces:**
    *   If you encounter issues with file or directory paths containing spaces, try enclosing the paths in double quotes when providing them as command-line arguments or in configuration files.
*   **Python Environment:**
    *   It's generally recommended to use a virtual environment (e.g., `venv`, `conda`) to manage project dependencies and avoid conflicts with other Python projects or system-wide packages.
