# Comprehensive Requirement & Request Log

This document chronicles every requirement, request, and constraint provided by the user throughout the development lifecycle of the "Music Downloader" application.

---

## 1. Initial Architecture & Objectives
*   **Role**: Senior Python Software Architect and DevOps Engineer.
*   **Objective**: Create a cohesive, production-ready, modular Python application named "Music Downloader".
*   **Tech Stack**:
    *   Python 3.11+ (Strict typing).
    *   GUI: `tkinter` (later upgraded to `customtkinter`).
    *   Config: `config.yaml`.
    *   Libraries: `faster_whisper` / `ctranslate2`, `yt_dlp`, `ffmpeg`, `mutagen`, `urllib` (MusicBrainz).
*   **Architecture**:
    *   Central Orchestrator (`main.py`).
    *   Modules: `ingest.py`, `enrichment.py`, `governance.py`.

## 2. Module Requirements

### Ingest Module (`ingest.py`)
*   **Tidal**: Primary source (High-Res/Master). Fallback if fails.
*   **MusicBrainz**: Fallback source if Tidal fails.
*   **Web Expansion**: Fallback to web search (YouTube via `yt-dlp`) if Tidal fails.
*   **YouTube Video**: Download corresponding Music Video for every audio track.
*   **Spotify**: Support importing from Spotify URLs (Track, Album, Playlist) and parsing XML.
*   **Deezer**: Add Deezer support as a fallback source (FLAC quality).
*   **Soulseek**: Add Soulseek support (via `slskd` API) with a service mode toggle.
*   **Search**: Implement scraping logic for song, album, artist, and playlist support.
*   **Logic**: Never download audio from YouTube (only video).

### Enrichment Module (`enrichment.py`)
*   **Audio Transcription**: Auto-transcribe audio using `faster_whisper` to generate `.lrc` (synced lyrics).
*   **Metadata Embedding**: Embed lyrics into audio tags immediately.
*   **Video Transcription**: Auto-transcribe video to generate `.srt` if subtitles are missing.
*   **Metadata Sync**: Transfer tags (Artist, Title, Album, Date) and Cover Art from Audio file to Video file.
*   **AI Settings**: Support VAD filtering and Beam Size configuration.

### Governance Module (`governance.py`)
*   **Directory Structure (Finalized)**:
    *   Music: `Output > Music > Artist > Album [Release Year] > Artist - Song.Format`
    *   Music Video: `Output > Music Videos > Artist - Song.Format`
    *   Sidecars: `.lrc` with audio, `.srt` with video.
*   **Validation**: Never archive a file unless it passes validation.
*   **Sanitization**: Enforce strict folder structures and metadata standardization.

## 3. Core Workflow ("The Smart Pipeline")
1.  **Tidal First**: Attempt download.
2.  **Deezer Fallback**: If Tidal fails.
3.  **MusicBrainz Fallback**: If both fail, use MB to find metadata, then manual/web search.
4.  **Audio Enrichment**: Transcribe to `.lrc`, embed metadata.
5.  **Video Acquisition**: Search YouTube using validated metadata (Artist - Title).
6.  **Metadata Sync**: Transfer audio tags/cover to video.
7.  **Video Enrichment**: Transcribe to `.srt`.
8.  **Archival**: Move to final governance structure.

## 4. GUI Requirements

### General
*   **Library**: Overhaul UI to `customtkinter` for modern appearance.
*   **Theme**: Native default Dark Mode with toggle.
*   **Responsiveness**: Window sizing must be adaptive/responsive.
*   **Browser**: Respect default web browser for links.

### Tab 1: Job Queue
*   **Table**: Dynamic, editable Treeview (Song, Artist, Album, Status).
*   **Controls**:
    *   Search/Add popup (Track, Album, Artist).
    *   Search Type Selection: Song, Artist, Album, URL.
    *   Import Button: Spotify/YouTube URLs, YouTube Cookies instructions.
    *   **Queue Management**: Allow reordering (Drag & Drop), removing items (Delete key/button), and multi-selection.
    *   **Progress**: Include progress bars for items in queue.

### Tab 2: Settings
*   **Configuration**: Include ALL options:
    *   Paths (Music, Video, Staging).
    *   Tokens: Tidal (Client ID, Secret, Token), Deezer (ARL), YouTube (Cookies).
    *   Formats: Audio (mp3, flac, aac), Video (mp4), Resolution (1080p).
    *   AI: Model Size (include `turbo`), Precision, Device (CUDA default), VAD, Beam Size.
    *   UI: Theme (Dark/Light), Search Results count.
    *   Concurrency: Download limit.
    *   Fallbacks: Toggle options.
    *   **Config Repair**: Tool/Button to restore defaults.

### Tab 3: Help
*   **Instructions**: How to extract Tidal/Deezer tokens and request Spotify GDPR/Cookies.

### Interactive Mode
*   **Checkbox**: Pause processing to show candidates.
*   **Workflow**:
    1.  Popup #1: Music Candidates (Cover Art, Metadata). User Selects.
    2.  Background: Download/Transcribe Audio.
    3.  Popup #2: Video Candidates (Thumbnail, Metadata). User Selects.
    4.  Background: Download/Transcribe Video.
    5.  Loop to next item.
*   **Features**: Modify Search button, Skip button, Thumbnail display (async).

## 5. Specific Logic & Constraints
*   **Dynamic Queue**: Handle items added during runtime (recursive expansion).
*   **Mock Detection**: If Tidal returns "Simulated Song", trigger fallback.
*   **Fallback Search**: If video search query is empty/generic, fallback to queue text.
*   **Integrity**: Validate files before archiving.
*   **Concurrency**: Add concurrent download limit option (Default: 1).
*   **Stop Logic**: "Stop" button must immediately delete current files not fully processed.
*   **Legacy**: Move existing `.pyw` scripts to `legacy/` folder.
*   **Dependencies**: Add system check for all dependencies (install missing, download Whisper model).

## 6. Bug Fixes & Refinements
*   **Tidal API**:
    *   Fix 400 Bad Request on search.
    *   Fix `AttributeError` on `get_url`.
    *   Implement OAuth Device Flow (Login Popup) to resolve connection issues.
    *   Add Client ID/Secret support.
*   **Deezer API**:
    *   Fix `AttributeError: 'Album' object has no attribute 'name'` (use `title`).
    *   Fix search method usage (`search_tracks`).
*   **YouTube**:
    *   Fix `yt-dlp` not downloading (ensure URL extraction and file verification).
    *   Fix search returning no results (use `extract_flat='in_playlist'`).
*   **Workflow Verification**:
    *   Test specific workflow for "AJR - Way Less Sad".
    *   Ensure exact folder output: `Music/AJR/OK Orchestra [2021]/AJR - Way Less Sad.flac`.

## 7. Deliverables
*   Full code for `main.py`, `modules/ingest.py`, `modules/enrichment.py`, `modules/governance.py`, `config.yaml`, `requirements.txt`.
*   Complete robust `README.md` with getting started guide.
