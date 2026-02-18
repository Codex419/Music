# Music Downloader - Production Pipeline

A cohesive, modular Python application designed to unify media acquisition, AI enrichment, and archival governance into a single, production-ready pipeline.

![Status](https://img.shields.io/badge/Status-Active-success)
![Python](https://img.shields.io/badge/Python-3.11%2B-blue)
![GUI](https://img.shields.io/badge/GUI-CustomTkinter-blueviolet)

## 🌟 Key Features

*   **Multi-Source Ingestion**:
    *   **Tidal**: High-Res/Master quality downloads (OAuth Login supported).
    *   **Deezer**: FLAC quality fallback (ARL Cookie supported).
    *   **YouTube**: Official Music Video acquisition (best video+audio).
    *   **Soulseek**: (Experimental) Integration for rare tracks via Slskd.
*   **AI Enrichment**:
    *   **faster-whisper**: Auto-generates synced lyrics (`.lrc`) from audio and subtitles (`.srt`) from video.
    *   **Metadata Sync**: Transfers tags and cover art from high-quality audio to music videos.
*   **Governance**:
    *   Standardized directory structure: `Music/Artist/Album [Year]/Artist - Song.ext`, `Music Videos/Artist - Song.ext`.
    *   Auto-sanitization of filenames.
*   **Modern GUI**:
    *   Dark Mode native interface (CustomTkinter).
    *   **Interactive Mode**: Manually approve or modify search results with rich metadata and thumbnails.
    *   **Queue Management**: Drag-and-drop reordering, progress bars, and batch processing.
    *   **Concurrency**: Multi-threaded processing for speed.

---

## 🚀 Getting Started

### Prerequisites

1.  **Python 3.11+**: Ensure Python is installed and added to PATH.
2.  **FFmpeg**: Required for media conversion and AI transcription.
    *   *Windows*: Download form gyan.dev, extract, and add `bin` folder to System PATH.
    *   *Linux/Mac*: `sudo apt install ffmpeg` / `brew install ffmpeg`.

### Installation

1.  **Clone the Repository**:
    ```bash
    git clone https://github.com/your-repo/music-downloader.git
    cd music-downloader
    ```

2.  **Install Dependencies**:
    The application includes a setup script to check and install missing packages.
    ```bash
    pip install -r requirements.txt
    ```
    *Alternatively, run `python main.py` and it will attempt to auto-install dependencies.*

---

## ⚙️ Configuration & Authentication

The application uses a `config.yaml` file for all settings. You can configure this via the **Settings** tab in the GUI.

### 1. Tidal (Priority Source)
To download High-Res audio, you need to authenticate with Tidal.
1.  Go to the **Settings** tab.
2.  Under "Tidal", click **Login to Tidal**.
3.  A popup will appear with a **User Code** and a link.
4.  Click **Open Link**, log in to Tidal in your browser, and authorize the device.
5.  Once confirmed, the application will auto-save your session tokens.

### 2. Deezer (Fallback Source)
If Tidal fails, the system falls back to Deezer.
1.  Log in to Deezer in your web browser.
2.  Open Developer Tools (`F12`) -> **Application** (or Storage) -> **Cookies**.
3.  Find the cookie named `arl`.
4.  Copy its value and paste it into **Settings** -> **Deezer** -> **ARL**.

### 3. YouTube (Music Videos)
To avoid age restrictions or throttling:
1.  Install the "Get cookies.txt LOCALLY" extension for your browser.
2.  Log in to YouTube.
3.  Use the extension to download `cookies.txt`.
4.  Place the file in the application folder or specify the path in **Settings**.

### 4. AI & Performance
*   **Model Size**: `medium` is recommended for a balance of speed and accuracy. Use `large-v2` for best results (requires ~3GB VRAM).
*   **Device**: Set to `cuda` if you have an NVIDIA GPU. Defaults to `auto`.
*   **Concurrency**: Number of simultaneous downloads (default: 1). Increase if you have fast internet and CPU.

---

## 🖥️ Usage Guide

### GUI Mode
Run the application:
```bash
python main.py
```

#### The Queue Tab
*   **Search**: Select type (`Song`, `Artist`, `Album`, `Url`).
    *   *Song*: Searches for specific track.
    *   *Artist/Album*: Expands into a list of tracks and adds them to the queue.
    *   *Url*: Paste a Spotify Track, Album, or Playlist URL to import.
*   **Management**:
    *   **Drag & Drop**: Reorder items in the queue.
    *   **Delete**: Click 'X' or press Delete key to remove items.
*   **Interactive Mode**: Check this box to inspect results before downloading.
    *   A popup will show candidates from Tidal/Deezer with Metadata and Cover Art.
    *   **Select**: Choose the correct match.
    *   **Modify**: Change the search query if no match is found.
    *   **Skip**: Ignore this item.

### CLI Mode
Run headless for scripting or server environments:
```bash
python main.py --search "AJR - Weak" --type song --no-gui
```
*   `--search`: Query string.
*   `--type`: `song`, `artist`, `album`, or `url`.
*   `--limit`: Max items to process (for batch expansion).

---

## 📂 Output Structure

The application strictly enforces the following archival structure:

**Audio:**
`Output/Music/{Artist}/{Album} [{Year}]/{Artist} - {Title}.flac`
`Output/Music/{Artist}/{Album} [{Year}]/{Artist} - {Title}.lrc`

**Video:**
`Output/Music Videos/{Artist} - {Title}.mp4`
`Output/Music Videos/{Artist} - {Title}.srt`

---

## 🔧 Troubleshooting

*   **Tidal 400 Bad Request**: This usually means the search query is too complex or the token is invalid. Try simplifying the search or re-logging in.
*   **YouTube Download Fail**: Ensure `ffmpeg` is installed. Update `yt-dlp` (`pip install -U yt-dlp`). Check if `cookies.txt` is expired.
*   **Import Errors**: If the app fails to start, ensure you have the C++ Build Tools installed (needed for some Python audio libraries).

---

## ⚖️ Disclaimer
This software is for educational and archival purposes only. Users are responsible for complying with the Terms of Service of the respective media platforms (Tidal, Deezer, YouTube). The developers do not endorse copyright infringement.
