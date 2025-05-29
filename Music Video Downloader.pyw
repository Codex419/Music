import os
import subprocess
import json
import logging
import sys
import re
import time
import threading
import queue
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext, simpledialog
import webbrowser
import io
import shutil # Still needed for potential future use? Maybe remove later if not used.

# --- Attempt to import dependencies ---
try:
    from mutagen.flac import FLAC
    from mutagen.mp3 import MP3
    from mutagen.id3 import ID3NoHeaderError
    from mutagen.mp4 import MP4
    from mutagen import MutagenError
    from mutagen.oggvorbis import OggVorbis
    from mutagen.oggopus import OggOpus
    MUTAGEN_AVAILABLE = True
except ImportError:
    MUTAGEN_AVAILABLE = False
    class FLAC: pass
    class MP3: pass
    class MP4: pass
    class ID3NoHeaderError(Exception): pass
    class MutagenError(Exception): pass
    class OggVorbis: pass
    class OggOpus: pass
    print("WARNING: Mutagen library not found.", file=sys.stderr)

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    print("WARNING: Requests library not found.", file=sys.stderr)

try:
    from PIL import Image, ImageTk, UnidentifiedImageError
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False
    class ImageTk:
        @staticmethod
        def PhotoImage(img): return None
    class UnidentifiedImageError(Exception): pass
    print("WARNING: Pillow (PIL) library not found.", file=sys.stderr)


# --- Constants ---
LOG_FILE = 'music_video_downloader_gui.log'
DEFAULT_VIDEO_QUALITY_FORMAT = 'bestvideo[height<=1080][ext=mp4]'
DEFAULT_AUDIO_QUALITY_FORMAT = 'bestaudio[ext=m4a]/bestaudio'
DEFAULT_COMBINED_FALLBACK_FORMAT = 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/bestvideo[height<=1080]+bestaudio/best[height<=1080]'
DEFAULT_SEARCH_RESULTS_COUNT = 5
DEFAULT_DOWNLOAD_DELAY = 2
THUMBNAIL_SIZE = (120, 90)
# Dark Mode Colors
BG_COLOR = '#2E2E2E'
FG_COLOR = '#EAEAEA'
ACCENT_COLOR = '#9B59B6' # Purple accent
SELECT_BG_COLOR = '#5E4B66' # Darker purple for selection background
ENTRY_BG_COLOR = '#3C3C3C' # Slightly lighter grey for entry fields
BUTTON_BG_COLOR = '#4A4A4A' # Grey for buttons
BUTTON_HOVER_BG = '#5A5A5A'
BUTTON_ACCENT_BG = '#8E44AD' # Lighter purple for button accents/hover
# MERGE_BUTTON_BG = '#C0392B' # No longer needed
# MERGE_BUTTON_HOVER_BG = '#E74C3C' # No longer needed

# Status Emojis/Text
STATUS_QUEUED = "⏳ Queued"; STATUS_PROCESSING = "⚙️ Processing..."; STATUS_SEARCHING = "🔍 Searching..."
STATUS_FILTERING = "🤔 Filtering..."; STATUS_DOWNLOADING = "⬇️ Downloading..."; STATUS_COMPLETE = "✅ Complete"
STATUS_FAILED_META = "❌ No Meta"; STATUS_FAILED_SEARCH = "❌ No Search Results"; STATUS_FAILED_FILTER = "❌ No Suitable Video"
STATUS_FAILED_DOWNLOAD = "❌ Download Failed"; STATUS_SKIPPED_MANUAL = "⏭️ Skipped (Manual)"; STATUS_EXISTS = "💾 Exists"
STATUS_ERROR = "🔥 Error"; STATUS_FAILED_ALL = "❌ Exhausted"
STATUS_NEEDS_REVIEW = "⚠️ Needs Review"; STATUS_REVIEWING = "👀 Reviewing..."
# STATUS_MERGED = "🚚 Merged" # No longer needed


# --- Logging Setup ---
log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
log_handler_file = logging.FileHandler(LOG_FILE, encoding='utf-8')
log_handler_file.setFormatter(log_formatter)
logger = logging.getLogger()
if logger.hasHandlers(): logger.handlers.clear()
logger.setLevel(logging.INFO) # Set to DEBUG for more verbose logs if needed
logger.addHandler(log_handler_file)


# --- Standalone Worker Functions ---
# (Worker functions remain the same)
def _get_startupinfo():
    startupinfo = None
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
    return startupinfo

def _worker_sanitize_filename(name):
    if not name: return "Untitled"
    name = re.sub(r'[\\/*?:"<>|]', "", name); name = re.sub(r'\.+', '.', name)
    name = name.strip().strip('.- ');
    if not name or name == ".": name = "Untitled"
    MAX_FILENAME_LEN = 200
    if len(name) > MAX_FILENAME_LEN:
         base, ext = os.path.splitext(name); base = base[:MAX_FILENAME_LEN - len(ext)]
         name = base + ext; logger.warning(f"Sanitized filename truncated: {name}")
    return name

def _worker_get_metadata(filepath):
    if not MUTAGEN_AVAILABLE: logger.error("Mutagen not available."); return None, None
    logger.debug(f"Reading metadata: {filepath}"); artist, title = None, None
    try:
        audio = None
        try: from mutagen import File; audio = File(filepath, easy=True)
        except Exception as e_load: logger.error(f"Mutagen load failed {filepath}: {e_load}"); return None, None
        if audio:
             artist = audio.get('artist', [None])[0]; title = audio.get('title', [None])[0]
             if not artist and hasattr(audio, 'tags') and audio.tags is not None:
                  tag_dict = audio.tags
                  if isinstance(audio, MP3): artist = (tag_dict.get('TPE1', [None])[0] or tag_dict.get('TPE2', [None])[0])
                  elif isinstance(audio, (FLAC, OggVorbis, OggOpus)): artist = tag_dict.get('artist', [None])[0]
                  elif isinstance(audio, MP4): artist = tag_dict.get('\xa9ART', [None])[0]
             if not title and hasattr(audio, 'tags') and audio.tags is not None:
                 tag_dict = audio.tags
                 if isinstance(audio, MP3): title = (tag_dict.get('TIT2', [None])[0] or tag_dict.get('TIT1', [None])[0])
                 elif isinstance(audio, (FLAC, OggVorbis, OggOpus)): title = tag_dict.get('title', [None])[0]
                 elif isinstance(audio, MP4): title = tag_dict.get('\xa9nam', [None])[0]
        else: logger.warning(f"Mutagen couldn't identify/read tags: {filepath}")
        if not artist or not title:
            logger.warning(f"Missing tags for {filepath}. Guessing from filename.")
            base = os.path.splitext(os.path.basename(filepath))[0]
            parts = re.split(r'\s+-\s+|\s+–\s+|\s*_\s*-\s*_\s*', base, 1)
            if len(parts) == 2:
                guessed_artist, guessed_title = parts[0].strip(), parts[1].strip()
                if guessed_artist and guessed_title and not guessed_artist.isdigit() and len(guessed_artist)>1 and len(guessed_title)>1:
                     if not artist: artist = guessed_artist
                     if not title: title = guessed_title
                     logger.info(f"Guessed from filename: A='{artist}', T='{title}'")
                else: logger.warning(f"Filename parse failed: '{base}'")
            else: logger.warning(f"Could not split filename: '{base}'")
        artist = artist.strip() if isinstance(artist, str) else None
        title = title.strip() if isinstance(title, str) else None
        if not artist or not title: logger.warning(f"Could not determine artist/title: {filepath}"); return None, None
        logger.debug(f"Metadata: Artist='{artist}', Title='{title}'"); return artist, title
    except MutagenError as e: logger.error(f"Mutagen error {filepath}: {e}"); return None, None
    except Exception as e: logger.error(f"Unexpected metadata error {filepath}: {e}", exc_info=True); return None, None

def _worker_search_videos(query, search_count, stop_event, gui_queue):
    command = ['yt-dlp', '--dump-json', '--no-playlist', '--match-filter', '!is_live & duration > 60 & duration < 1200', '--ignore-errors', '--no-warnings', '--extractor-args', 'youtube:player_client=web', f'ytsearch{search_count}:{query}']
    logger.info(f"Searching YouTube for: \"{query}\"")
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', startupinfo=_get_startupinfo())
        stdout, stderr = process.communicate(timeout=60)
        if stop_event.is_set(): return []
        if process.returncode != 0:
            if "HTTP Error 429" in stderr: logger.error(f"yt-dlp search failed: Rate limited (HTTP 429).")
            else: logger.error(f"yt-dlp search failed (code {process.returncode}) for query '{query}'. Stderr: {stderr.strip()}")
            return None
        videos = []
        for line in stdout.strip().split('\n'):
            if line:
                try: videos.append(json.loads(line))
                except json.JSONDecodeError: logger.warning(f"Failed to parse JSON line: {line[:100]}...")
        logger.info(f"Found {len(videos)} potential video(s) for '{query}'"); return videos
    except FileNotFoundError: logger.critical("🚨 yt-dlp not found."); gui_queue.put({'type': 'error_message', 'data': {'message': "yt-dlp not found. Install/add to PATH."}}); return None
    except subprocess.TimeoutExpired: logger.error(f"yt-dlp search timed out for query '{query}'."); return []
    except Exception as e: logger.error(f"Error running yt-dlp search for query '{query}': {e}", exc_info=True); return None

# Modified to handle "No Trust Mode" and return dict indicating action needed
def _worker_filter_and_select(videos, artist, title, gui_queue, is_override=False, no_trust_mode=False):
    """
    Analyzes results, extracts thumbnail. Prioritizes official videos unless no_trust_mode.
    Returns:
        - video_id (str): If automatically selected (only if no_trust_mode is False).
        - {'needs_manual': True, 'reason': 'select'/'override', 'candidates': candidates, 'artist': artist, 'title': title}: If manual action needed.
        - None: If no suitable candidates found after filtering.
    """
    if not videos: return None
    candidates = []; artist_lower, title_lower = artist.lower(), title.lower()
    negative_keywords = [
        'lyric', 'cover', 'remix', 'live', 'reaction', 'audio only', 'visualizer',
        'fan cam', 'instrumental', 'karaoke', 'parody', 'chipmunk', 'slowed',
        'reverb', 'bass boosted', 'tutorial', 'lesson', 'interview', 'teaser',
        'trailer', 'album version', 'full album', 'topic', 'provided to youtube by',
        '8d audio', 'nightcore', 'extended', 'mashup', 'megamix', 'clean'
    ]
    positive_keywords = ['official music video', 'official video']

    # --- If No Trust Mode, skip all filtering/priority checks ---
    if no_trust_mode:
        logger.info("No Trust Mode: Preparing all results for manual selection.")
        for video in videos:
            vid_title_raw = video.get('title'); vid_title = vid_title_raw if isinstance(vid_title_raw, str) else ''
            channel_raw = video.get('channel', video.get('uploader')); channel = channel_raw if isinstance(channel_raw, str) else ''
            thumbnail_url = None; thumbnails = video.get('thumbnails')
            if isinstance(thumbnails, list) and thumbnails:
                thumbnail_url = thumbnails[-1].get('url')
                if not thumbnail_url:
                     for thumb in reversed(thumbnails): thumbnail_url = thumb.get('url');
                     if thumbnail_url: break
            if not thumbnail_url: thumbnail_url = video.get('thumbnail')
            candidates.append({'id': video.get('id'), 'title': vid_title, 'channel': channel,
                               'duration': video.get('duration'),
                               'url': video.get('webpage_url', f"https://www.youtube.com/watch?v={video.get('id')}" if video.get('id') else '#'),
                               'score': 'N/A', 'views': video.get('view_count'), 'thumbnail': thumbnail_url})
        if not candidates: return None # Should not happen if videos had items
        return {'needs_manual': True, 'reason': 'select', 'candidates': candidates, 'artist': artist, 'title': title}


    # --- Priority Check for Official Video (only if not no_trust_mode) ---
    if not is_override:
        for video in videos:
            vid_title_raw = video.get('title'); vid_title = vid_title_raw if isinstance(vid_title_raw, str) else ''; vid_title_lower = vid_title.lower()
            channel_raw = video.get('channel', video.get('uploader')); channel = channel_raw if isinstance(channel_raw, str) else ''; channel_lower = channel.lower()
            uploader_id_raw = video.get('uploader_id'); uploader_id = uploader_id_raw.lower() if isinstance(uploader_id_raw, str) else ''
            is_verified = video.get('channel_is_verified', False)
            is_official_title = any(pk in vid_title_lower for pk in positive_keywords)
            is_official_channel = (channel_lower == artist_lower or 'official' in channel_lower or 'vevo' in channel_lower or 'vevo' in uploader_id or is_verified)
            has_negative = any(nk in vid_title_lower for nk in negative_keywords if nk not in ['audio only', 'visualizer'])
            if is_official_title and is_official_channel and not has_negative:
                 video_id = video.get('id')
                 if video_id: logger.info(f"Prioritized official video: '{vid_title}'"); return video_id

    # --- Continue with normal filtering/scoring ---
    for video in videos:
        vid_title_raw = video.get('title'); vid_title = vid_title_raw if isinstance(vid_title_raw, str) else ''; vid_title_lower = vid_title.lower()
        channel_raw = video.get('channel', video.get('uploader')); channel = channel_raw if isinstance(channel_raw, str) else ''; channel_lower = channel.lower()
        uploader_id_raw = video.get('uploader_id'); uploader_id = uploader_id_raw.lower() if isinstance(uploader_id_raw, str) else ''
        description_raw = video.get('description'); description = description_raw.lower() if isinstance(description_raw, str) else ''
        thumbnail_url = None; thumbnails = video.get('thumbnails')
        if isinstance(thumbnails, list) and thumbnails:
            thumbnail_url = thumbnails[-1].get('url')
            if not thumbnail_url:
                 for thumb in reversed(thumbnails):
                      thumbnail_url = thumb.get('url')
                      if thumbnail_url: break
        if not thumbnail_url: thumbnail_url = video.get('thumbnail')

        candidate_data = {'id': video.get('id'), 'title': vid_title, 'channel': channel, 'duration': video.get('duration'),
                          'url': video.get('webpage_url', f"https://www.youtube.com/watch?v={video.get('id')}" if video.get('id') else '#'),
                          'views': video.get('view_count'), 'thumbnail': thumbnail_url}

        if is_override:
            candidate_data['score'] = 'N/A'
            candidates.append(candidate_data)
            continue

        # Normal Filtering Logic
        score, is_negative = 0, False
        if any(keyword in vid_title_lower for keyword in negative_keywords): is_negative = True; score -= (5 if any(pk in vid_title_lower for pk in positive_keywords) else 20)
        if not is_negative and description and any(keyword in description for keyword in ['lyrics in description', 'fan-made', 'unofficial']): is_negative = True; score -= 5
        if any(keyword in vid_title_lower for keyword in positive_keywords): score += 10
        if channel_lower == artist_lower or 'official' in channel_lower or 'vevo' in channel_lower or 'vevo' in uploader_id: score += 8
        elif artist_lower in channel_lower: score += 5
        elif 'topic' in channel_lower or 'various artists' in channel_lower: score -= 5
        has_artist = artist_lower in vid_title_lower; has_title = title_lower in vid_title_lower
        if has_artist and has_title: score += 4
        elif has_title: score += 2
        view_count = video.get('view_count')
        if view_count:
            if view_count > 10000000: score += 3
            elif view_count > 1000000: score += 2
            elif view_count > 100000: score += 1
        if video.get('channel_is_verified', False): score += 5
        duration = video.get('duration')
        if duration:
             if duration < 90: score -= 2
             if duration > 600: score -= 2

        if not is_negative and (has_title or score > 2):
            candidate_data['score'] = score
            candidates.append(candidate_data)

    if not candidates: logger.info("No suitable candidates found after filtering."); return None

    if not is_override:
        candidates.sort(key=lambda x: x['score'], reverse=True)
        if len(candidates) == 1 and candidates[0]['score'] >= 8: logger.info(f"Auto selected (single): '{candidates[0]['title']}'"); return candidates[0].get('id')
        if len(candidates) > 1 and candidates[0]['score'] >= candidates[1]['score'] + 7 and candidates[0]['score'] >= 12: logger.info(f"Auto selected (clear winner): '{candidates[0]['title']}'"); return candidates[0].get('id')

    if not candidates:
        logger.info("No videos provided for manual selection.")
        return None

    review_reason = 'override' if is_override else 'select'
    logger.info(f"Signalling manual action needed (reason: {review_reason}).")
    return {'needs_manual': True, 'reason': review_reason, 'candidates': candidates, 'artist': artist, 'title': title}


# --- UPDATED: perform_download finds file in directory ---
def perform_download(video_id, sanitized_artist, sanitized_title, output_dir, final_quality_format, gui_queue):
    """
    Synchronously downloads the video using yt-dlp. Finds the downloaded file in the output directory.
    Returns (success_bool, final_full_path_or_None).
    """
    if not video_id: logger.error("Download attempt with missing video ID."); return False, None
    # --- Output template now uses the flat output_dir ---
    output_template = os.path.join(output_dir, f"{sanitized_artist} - {sanitized_title}.%(ext)s")
    expected_prefix = f"{sanitized_artist} - {sanitized_title}." # Used to find the file later

    # Command without --print filename
    command = ['yt-dlp', '-f', final_quality_format, '-o', output_template, '--no-warnings', '--ignore-errors', '--force-overwrites', '--no-part', '--concurrent-fragments', '4', '--', f'https://www.youtube.com/watch?v={video_id}']
    logger.info(f"Attempting download: ID {video_id} for '{sanitized_artist} - {sanitized_title}' to '{output_dir}'")
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', startupinfo=_get_startupinfo())
        stdout, stderr = process.communicate(timeout=600) # Wait for download to finish

        if process.returncode == 0:
            logger.info(f"yt-dlp process completed successfully for {video_id}. Verifying file presence...")
            # --- Find the downloaded file ---
            found_path = None
            is_windows = sys.platform == "win32"
            expected_prefix_lower = expected_prefix.lower() if is_windows else expected_prefix

            for attempt in range(5): # Try for ~1 second total
                try:
                    if os.path.isdir(output_dir):
                        for filename in os.listdir(output_dir):
                            match_name = filename.lower() if is_windows else filename
                            if match_name.startswith(expected_prefix_lower):
                                found_path = os.path.join(output_dir, filename)
                                logger.info(f"Found downloaded file: {found_path}")
                                break # Exit inner loop
                        if found_path:
                             break # Exit outer loop
                    else:
                         logger.warning(f"Output directory {output_dir} doesn't exist or isn't a directory during file check.")
                         break # Don't retry if dir is bad
                except Exception as list_err:
                    logger.warning(f"Error listing directory {output_dir} on attempt {attempt+1}: {list_err}")

                if not found_path:
                    logger.debug(f"File check attempt {attempt+1}/5 failed for prefix '{expected_prefix}' in {output_dir}, waiting...")
                    time.sleep(0.2 * (attempt + 1))
            # --- End file finding ---

            if found_path:
                return True, found_path
            else:
                logger.error(f"Download process succeeded for {video_id} but could not find file matching prefix '{expected_prefix}' in {output_dir} after retries.")
                return False, None
        else:
            logger.error(f"yt-dlp download failed {video_id}. Code: {process.returncode}. Stderr: {stderr.strip()}")
            if gui_queue:
                if "requested format not available" in stderr.lower(): gui_queue.put({'type': 'error_message', 'data': {'message': f"Download failed '{sanitized_title}':\nFormat not available."}})
                elif "ffmpeg" in stderr.lower() or "ffprobe" in stderr.lower(): gui_queue.put({'type': 'error_message', 'data': {'message': f"Download failed '{sanitized_title}':\nIssue with FFmpeg/FFprobe."}})
            return False, None
    except subprocess.TimeoutExpired: logger.error(f"yt-dlp download timed out: {video_id}."); return False, None
    except FileNotFoundError:
        logger.critical("🚨 yt-dlp not found during download.")
        if gui_queue:
            gui_queue.put({'type': 'error_message', 'data': {'message': "yt-dlp not found."}})
        return False, None
    except Exception as e: logger.error(f"Unexpected download error {video_id}: {e}", exc_info=True); return False, None

# Function remains the same
def perform_search(query, search_count):
    """Synchronously searches YouTube using yt-dlp. Returns list or None on error."""
    command = ['yt-dlp', '--dump-json', '--no-playlist', '--match-filter', '!is_live & duration > 60 & duration < 1200', '--ignore-errors', '--no-warnings', '--extractor-args', 'youtube:player_client=web', f'ytsearch{search_count}:{query}']
    logger.info(f"Searching YouTube for: \"{query}\"")
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', startupinfo=_get_startupinfo())
        stdout, stderr = process.communicate(timeout=60)
        if process.returncode != 0:
            if "HTTP Error 429" in stderr: logger.error(f"yt-dlp search failed: Rate limited (HTTP 429).")
            else: logger.error(f"yt-dlp search failed (code {process.returncode}) for query '{query}'. Stderr: {stderr.strip()}")
            return None
        videos = []
        for line in stdout.strip().split('\n'):
            if line:
                try: videos.append(json.loads(line))
                except json.JSONDecodeError: logger.warning(f"Failed to parse JSON line: {line[:100]}...")
        logger.info(f"Found {len(videos)} potential video(s) for '{query}'"); return videos
    except FileNotFoundError: logger.critical("🚨 yt-dlp not found."); return None # Can't send to GUI queue from here
    except subprocess.TimeoutExpired: logger.error(f"yt-dlp search timed out for query '{query}'."); return []
    except Exception as e: logger.error(f"Error running yt-dlp search for query '{query}': {e}", exc_info=True); return None

# --- UPDATED: worker_thread_main checks input dir first and uses single output dir ---
def worker_thread_main(music_dir, output_dir_base, options, filepaths, gui_queue, manual_select_queue, stop_event, interactive_mode):
    """Main function for the background processing thread."""
    total_files = len(filepaths); processed_count = 0; error_occurred = None
    override_existing = options.get('override_existing', False) # Get override flag
    no_trust_mode = options.get('no_trust_mode', False) # Get no trust flag

    try:
        for filepath in filepaths:
            if stop_event.is_set(): logger.info("Stop event detected at start of loop iteration."); break
            processed_count += 1
            gui_queue.put({'type': 'progress_update', 'data': {'current': processed_count, 'total': total_files}})
            gui_queue.put({'type': 'status_update', 'data': {'filepath': filepath, 'status': STATUS_PROCESSING, 'message': 'Reading metadata...'}})

            artist, title = _worker_get_metadata(filepath)
            if not artist or not title: gui_queue.put({'type': 'status_update', 'data': {'filepath': filepath, 'status': STATUS_FAILED_META}}); continue
            if stop_event.is_set(): break

            video_already_exists = False
            # --- UPDATED Existing File Check ---
            if not override_existing: # Only check if override is OFF
                sanitized_artist = _worker_sanitize_filename(artist); sanitized_title = _worker_sanitize_filename(title)
                filename_prefix_base = f"{sanitized_artist} - {sanitized_title}."
                is_windows = sys.platform == "win32"
                filename_prefix_lower = filename_prefix_base.lower() if is_windows else filename_prefix_base

                # 1. Check Input Directory first
                input_dir = os.path.dirname(filepath)
                try:
                    if os.path.isdir(input_dir):
                        for existing_file in os.listdir(input_dir):
                             match_name = existing_file.lower() if is_windows else existing_file
                             if match_name.startswith(filename_prefix_lower) and os.path.splitext(match_name)[1].lower() in ['.mp4', '.mkv', '.webm', '.mov', '.avi', '.wmv', '.flv']: # Check common video extensions
                                 logger.info(f"Video exists in INPUT directory: '{existing_file}'. Skipping.")
                                 gui_queue.put({'type': 'status_update', 'data': {'filepath': filepath, 'status': STATUS_EXISTS}})
                                 video_already_exists = True
                                 break
                except Exception as e:
                    logger.warning(f"Error checking input directory {input_dir} for existing file: {e}")

                if video_already_exists: continue # Skip if found in input dir

                # 2. Check Output Directory (always output_dir_base now)
                current_output_dir = output_dir_base # Use the single output dir
                if os.path.normpath(current_output_dir) != os.path.normpath(input_dir): # Only check output if it's different
                    try:
                        if os.path.isdir(current_output_dir):
                            for existing_file in os.listdir(current_output_dir):
                                 match_name = existing_file.lower() if is_windows else existing_file
                                 if match_name.startswith(filename_prefix_lower) and os.path.splitext(match_name)[1].lower() in ['.mp4', '.mkv', '.webm', '.mov', '.avi', '.wmv', '.flv']:
                                     logger.info(f"Video exists in OUTPUT directory: '{existing_file}'. Skipping.")
                                     gui_queue.put({'type': 'status_update', 'data': {'filepath': filepath, 'status': STATUS_EXISTS}})
                                     video_already_exists = True
                                     break
                    except Exception as e:
                        logger.warning(f"Error checking output directory {current_output_dir} for existing file: {e}")

                if video_already_exists: continue # Skip if found in output dir
            else:
                logger.info(f"Override enabled, skipping existing file check for {filepath}")

            # --- Set current_output_dir for download ---
            current_output_dir = output_dir_base
            # --- End Updated Check ---

            if stop_event.is_set(): break

            # --- Search/Filter/Select/Download Sequence ---
            selected_video_id = None
            final_status = None # Track the final outcome for this file
            search_error = False
            needs_manual_action = False # Flag if any step needs manual input
            action_reason = None # 'select', 'override', 'search'
            action_candidates = [] # Candidates for selection dialogs
            downloaded_file_path = None # Store the actual full file path after download
            videos_found_at_all = False # Track if any search returned results

            # --- Attempt 1: Official Search + Filter (Skip filter if no_trust_mode) ---
            gui_queue.put({'type': 'status_update', 'data': {'filepath': filepath, 'status': STATUS_SEARCHING, 'message': 'Official search...'}})
            search_query_official = f"{artist} - {title} official music video"
            videos = _worker_search_videos(search_query_official, options['search_results_count'], stop_event, gui_queue)
            if stop_event.is_set(): break
            if videos is None: search_error = True
            elif videos:
                videos_found_at_all = True
                if no_trust_mode: # Force manual select with these results
                     filter_result = _worker_filter_and_select(videos, artist, title, gui_queue, is_override=True, no_trust_mode=True)
                     if isinstance(filter_result, dict) and filter_result.get('needs_manual'):
                          needs_manual_action = True; action_reason = filter_result['reason']; action_candidates = filter_result['candidates']
                     else: logger.warning("No Trust Mode filter returned unexpected result."); final_status = STATUS_FAILED_FILTER
                else: # Normal filtering
                    gui_queue.put({'type': 'status_update', 'data': {'filepath': filepath, 'status': STATUS_FILTERING}})
                    filter_result = _worker_filter_and_select(videos, artist, title, gui_queue)
                    if isinstance(filter_result, str): selected_video_id = filter_result
                    elif isinstance(filter_result, dict) and filter_result.get('needs_manual'):
                        needs_manual_action = True; action_reason = filter_result['reason']; action_candidates = filter_result['candidates']
                    else: logger.info(f"Initial filter rejected all videos for '{title}'.")
            else: logger.info(f"Initial search yielded no results for '{title}'.")

            # --- Attempt 2: Fallback Search + Filter (if needed and not no_trust_mode) ---
            if selected_video_id is None and not needs_manual_action and not search_error and not stop_event.is_set() and not no_trust_mode:
                logger.info(f"Trying fallback search for '{title}'.")
                gui_queue.put({'type': 'status_update', 'data': {'filepath': filepath, 'status': STATUS_SEARCHING, 'message': 'Fallback search...'}})
                search_query_simple = f"{artist} - {title}"
                videos = _worker_search_videos(search_query_simple, options['search_results_count'], stop_event, gui_queue)
                if stop_event.is_set(): break
                if videos is None: search_error = True
                elif videos:
                    videos_found_at_all = True
                    gui_queue.put({'type': 'status_update', 'data': {'filepath': filepath, 'status': STATUS_FILTERING, 'message': 'Filtering fallback...'}})
                    filter_result = _worker_filter_and_select(videos, artist, title, gui_queue)
                    if isinstance(filter_result, str): selected_video_id = filter_result
                    elif isinstance(filter_result, dict) and filter_result.get('needs_manual'):
                        needs_manual_action = True; action_reason = filter_result['reason']; action_candidates = filter_result['candidates']
                    else: logger.info(f"Fallback filter rejected all videos for '{title}'.")
                # else: Fallback search found nothing

            # --- Attempt 3: Unfiltered Select or Manual Search (if needed and not no_trust_mode) ---
            if selected_video_id is None and not needs_manual_action and not search_error and not stop_event.is_set() and not no_trust_mode:
                if videos_found_at_all:
                    logger.info(f"Searches found videos, but filter rejected them for '{title}'. Triggering unfiltered selection.")
                    search_query_simple = f"{artist} - {title}"
                    videos_unfiltered = _worker_search_videos(search_query_simple, options['search_results_count'], stop_event, gui_queue)
                    if stop_event.is_set(): break
                    if videos_unfiltered is None: search_error = True
                    elif videos_unfiltered:
                        filter_result = _worker_filter_and_select(videos_unfiltered, artist, title, gui_queue, is_override=True)
                        if isinstance(filter_result, dict) and filter_result.get('needs_manual'):
                            needs_manual_action = True; action_reason = filter_result['reason']; action_candidates = filter_result['candidates']
                        else: logger.warning("Filter returned unexpected result in unfiltered override."); final_status = STATUS_FAILED_FILTER
                    else: logger.info("Unfiltered search attempt found nothing."); final_status = STATUS_FAILED_SEARCH
                else:
                    logger.info(f"No videos found automatically for '{title}'.")
                    if interactive_mode:
                        gui_queue.put({'type': 'ask_manual_search', 'data': {'artist': artist, 'title': title, 'filepath': filepath}})
                        logger.debug("Worker (Interactive): Waiting for manual search query..."); manual_query_result = manual_select_queue.get(); logger.info(f"Worker (Interactive): Manual query result: {manual_query_result}")
                        if manual_query_result == "stop_signal": stop_event.set(); break
                        if manual_query_result == "quit": stop_event.set(); break
                        manual_query = None
                        if manual_query_result == "__FILENAME_SEARCH__": manual_query = os.path.splitext(os.path.basename(filepath))[0]; logger.info(f"Using filename for manual search: '{manual_query}'")
                        elif isinstance(manual_query_result, str): manual_query = manual_query_result
                        if manual_query:
                            gui_queue.put({'type': 'status_update', 'data': {'filepath': filepath, 'status': STATUS_SEARCHING, 'message': 'Manual search...'}})
                            videos_manual = _worker_search_videos(manual_query, options['search_results_count'], stop_event, gui_queue)
                            if stop_event.is_set(): break
                            if videos_manual is None: final_status = STATUS_ERROR
                            elif videos_manual:
                                 gui_queue.put({'type': 'status_update', 'data': {'filepath': filepath, 'status': STATUS_FILTERING, 'message': 'Override selection?'}})
                                 filter_result = _worker_filter_and_select(videos_manual, artist, title, gui_queue, is_override=True)
                                 if isinstance(filter_result, dict) and filter_result.get('needs_manual'):
                                     filter_result['filepath'] = filepath
                                     gui_queue.put({'type': 'ask_manual_select', 'data': filter_result})
                                     logger.debug("Worker (Interactive): Waiting for override selection..."); selected_video_id = manual_select_queue.get(); logger.info(f"Worker (Interactive): Override selection result: {selected_video_id}")
                                     if selected_video_id == "stop_signal": stop_event.set(); break
                                     if selected_video_id == "quit": stop_event.set(); break
                                 else: logger.warning("Filter returned unexpected result in override."); final_status = STATUS_FAILED_FILTER
                            else: final_status = STATUS_FAILED_SEARCH
                        else: final_status = STATUS_SKIPPED_MANUAL
                    else: # Review Mode - Queue for manual search
                        logger.info(f"Queueing '{title}' for manual search review (no results found).")
                        review_payload = {'needs_manual': True, 'reason': 'search', 'filepath': filepath, 'artist': artist, 'title': title, 'candidates': []}
                        gui_queue.put({'type': 'review_needed', 'data': review_payload}); final_status = STATUS_NEEDS_REVIEW

            # --- Handle Manual Action (if flagged and not already handled by interactive manual search) ---
            if needs_manual_action and selected_video_id is None and final_status is None and not stop_event.is_set():
                 if interactive_mode:
                     manual_data = {'candidates': action_candidates, 'artist': artist, 'title': title, 'filepath': filepath, 'is_override': (action_reason == 'override')} # Pass filepath
                     gui_queue.put({'type': 'ask_manual_select', 'data': manual_data})
                     logger.debug(f"Worker (Interactive): Waiting for final selection (Reason: {action_reason})...");
                     selected_video_id = manual_select_queue.get()
                     logger.info(f"Worker (Interactive): Final selection result: {selected_video_id}")
                     if selected_video_id == "stop_signal": stop_event.set(); break
                     if selected_video_id == "quit": stop_event.set(); break
                 else: # Review Mode
                     logger.info(f"Queueing '{title}' for manual review ({action_reason}).")
                     review_payload = {'needs_manual': True, 'reason': action_reason, 'candidates': action_candidates, 'artist': artist, 'title': title, 'filepath': filepath}
                     gui_queue.put({'type': 'review_needed', 'data': review_payload}); final_status = STATUS_NEEDS_REVIEW

            # --- Final Outcome Processing ---
            if stop_event.is_set(): break

            if selected_video_id: # Video was selected (auto or manual interactive)
                # 4. Construct Output Path (always output_dir_base now)
                try:
                    # Ensure the single output directory exists
                    if not os.path.exists(output_dir_base): os.makedirs(output_dir_base); logger.info(f"Created output directory: {output_dir_base}")
                    elif not os.path.isdir(output_dir_base): logger.error(f"Output path {output_dir_base} not a directory."); final_status = STATUS_ERROR; gui_queue.put({'type': 'status_update', 'data': {'filepath': filepath, 'status': final_status, 'message': 'Output Dir Error'}}); continue
                    current_output_dir = output_dir_base # Set for download function
                except Exception as e:
                    logger.error(f"Failed output directory check/creation {output_dir_base}: {e}", exc_info=True)
                    final_status = STATUS_ERROR
                    gui_queue.put({'type': 'status_update', 'data': {'filepath': filepath, 'status': final_status, 'message': 'Output Dir Error'}})
                    continue
                if stop_event.is_set(): break

                # 5. Download Video
                gui_queue.put({'type': 'status_update', 'data': {'filepath': filepath, 'status': STATUS_DOWNLOADING}})
                sanitized_artist = _worker_sanitize_filename(artist); sanitized_title = _worker_sanitize_filename(title)
                download_success, downloaded_file_path = perform_download(selected_video_id, sanitized_artist, sanitized_title, current_output_dir, options['final_quality_format'], gui_queue)
                if stop_event.is_set(): break
                if download_success:
                    final_status = STATUS_COMPLETE
                    # Store info (not needed for merge, but maybe useful later)
                    gui_queue.put({'type': 'store_merge_info', 'data': {'filepath': filepath, 'downloaded_full_path': downloaded_file_path}})
                else:
                    final_status = STATUS_FAILED_DOWNLOAD
                gui_queue.put({'type': 'status_update', 'data': {'filepath': filepath, 'status': final_status}})

            elif final_status is None: # No ID selected, not queued for review, no error yet
                 if search_error: final_status = STATUS_ERROR
                 else: final_status = STATUS_FAILED_ALL # Default failure if nothing else applies
                 gui_queue.put({'type': 'status_update', 'data': {'filepath': filepath, 'status': final_status}})

            # Polite delay (only if not stopped and not just queued for review)
            if not stop_event.is_set() and final_status != STATUS_NEEDS_REVIEW:
                delay_step = 0.1; total_delay = options['download_delay']; elapsed_delay = 0
                while elapsed_delay < total_delay:
                     if stop_event.is_set(): break
                     time.sleep(delay_step); elapsed_delay += delay_step

    except Exception as e:
        logger.error(f"Unhandled error in worker thread: {e}", exc_info=True)
        error_occurred = str(e)
        try: gui_queue.put({'type': 'error_message', 'data': {'message': f"Critical background error:\n{e}"}})
        except Exception as qe: logger.error(f"Failed to put critical error message in queue: {qe}")
    finally:
        logger.info("Worker thread finishing initial pass.")
        try: gui_queue.put({'type': 'initial_pass_complete', 'data': {'error': error_occurred}})
        except Exception as qe: logger.error(f"Failed to put completion message in queue: {qe}")


# --- Tooltip Class ---
# (Remains the same)
class ToolTip:
    def __init__(self, widget, text):
        self.widget = widget; self.text = text; self.tooltip_window = None
        widget.bind("<Enter>", self.show_tooltip); widget.bind("<Leave>", self.hide_tooltip)
    def show_tooltip(self, event=None):
        if not self.widget.winfo_exists(): return
        x, y, _, _ = self.widget.bbox("insert"); x += self.widget.winfo_rootx() + 20; y += self.widget.winfo_rooty() + self.widget.winfo_height() + 5
        if self.tooltip_window: self.tooltip_window.destroy()
        self.tooltip_window = tk.Toplevel(self.widget)
        if not self.tooltip_window.winfo_exists(): self.tooltip_window = None; return
        self.tooltip_window.wm_overrideredirect(True); self.tooltip_window.wm_geometry(f"+{x}+{y}")
        label = tk.Label(self.tooltip_window, text=self.text, justify='left', background="#ffffe0", relief='solid', borderwidth=1, wraplength=300)
        label.pack(ipadx=1)
    def hide_tooltip(self, event=None):
        if self.tooltip_window:
            if self.tooltip_window.winfo_exists(): self.tooltip_window.destroy()
            self.tooltip_window = None

# --- GUI Log Handler ---
# (Remains the same)
class GuiLogHandler(logging.Handler):
    def __init__(self, text_widget):
        logging.Handler.__init__(self); self.text_widget = text_widget; self.queue = queue.Queue()
        if self.text_widget.winfo_exists(): self.text_widget.after(100, self.poll_log_queue)
    def emit(self, record): self.queue.put(self.format(record))
    def poll_log_queue(self):
        while True:
            try: record = self.queue.get(block=False)
            except queue.Empty: break
            else:
                if self.text_widget.winfo_exists():
                    try:
                        self.text_widget.configure(state='normal'); self.text_widget.insert(tk.END, record + '\n')
                        self.text_widget.configure(state='disabled'); self.text_widget.yview(tk.END)
                    except tk.TclError as e: logger.warning(f"TclError updating log widget: {e}"); break
        if self.text_widget.winfo_exists(): self.text_widget.after(100, self.poll_log_queue)

# --- Manual Selection Dialog ---
# --- UPDATED: Added URL Entry and Button ---
class ManualSelectDialog(tk.Toplevel):
    def __init__(self, parent, result_queue, candidates, artist, title, filepath, is_override=False): # Added filepath
        super().__init__(parent)
        if not parent.winfo_exists(): self.destroy(); return
        self.transient(parent); self.grab_set(); self.result = None; self.result_queue = result_queue
        dialog_title = f"{'Override ' if is_override else ''}Manual Selection: {artist} - {title}"
        self.title(dialog_title); self.geometry("750x600"); # Increased height slightly
        self.columnconfigure(0, weight=1); self.rowconfigure(0, weight=1) # Main content row expands
        self.candidates = candidates; self.thumbnail_cache = {}; self.is_override = is_override
        self.filepath = filepath # Store original filepath
        self.artist = artist # Store for potential title updates
        self.title_str = title # Store for potential title updates

        # --- Main Content Frame ---
        main_frame = ttk.Frame(self); main_frame.grid(row=0, column=0, sticky=tk.NSEW, padx=5, pady=5)
        main_frame.columnconfigure(0, weight=1); main_frame.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(main_frame, borderwidth=0); self.scrollbar = ttk.Scrollbar(main_frame, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = ttk.Frame(self.canvas)
        self.scrollable_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")) if self.canvas.winfo_exists() else None)
        self.canvas_frame = self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set); self.canvas.grid(row=0, column=0, sticky=tk.NSEW); self.scrollbar.grid(row=0, column=1, sticky=tk.NS)
        self.canvas.bind("<MouseWheel>", self._on_mousewheel); self.canvas.bind("<Button-4>", self._on_mousewheel); self.canvas.bind("<Button-5>", self._on_mousewheel)
        self.scrollable_frame.bind("<MouseWheel>", self._on_mousewheel); self.scrollable_frame.bind("<Button-4>", self._on_mousewheel); self.scrollable_frame.bind("<Button-5>", self._on_mousewheel)
        self.bind("<Configure>", self._on_frame_configure)
        self.populate_candidates()

        # --- URL Override Frame ---
        url_frame = ttk.Frame(self, padding="5"); url_frame.grid(row=1, column=0, sticky=tk.EW, padx=5, pady=(5,0))
        url_frame.columnconfigure(1, weight=1)
        ttk.Label(url_frame, text="Override URL:").grid(row=0, column=0, padx=(0,5), pady=5, sticky=tk.W)
        self.url_entry_var = tk.StringVar()
        url_entry = ttk.Entry(url_frame, textvariable=self.url_entry_var, width=60); url_entry.grid(row=0, column=1, padx=5, pady=5, sticky=tk.EW)
        ToolTip(url_entry, "Paste a specific YouTube video URL here to use instead.")
        use_url_button = ttk.Button(url_frame, text="Use URL", command=self.use_url); use_url_button.grid(row=0, column=2, padx=(5,0), pady=5)
        ToolTip(use_url_button, "Select the video from the pasted URL.")

        # --- Bottom Buttons Frame ---
        button_frame = ttk.Frame(self, padding="5"); button_frame.grid(row=2, column=0, sticky=tk.EW, padx=5, pady=5)
        button_frame.columnconfigure(0, weight=1); button_frame.columnconfigure(1, weight=1); button_frame.columnconfigure(2, weight=1)
        filename_search_button = ttk.Button(button_frame, text="Search by Filename", command=self.search_by_filename); filename_search_button.grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        ToolTip(filename_search_button, "Search YouTube using the original audio filename.")
        skip_button = ttk.Button(button_frame, text="Skip This Song", command=self.on_skip); skip_button.grid(row=0, column=1, padx=5, pady=5) # Middle button

        self.protocol("WM_DELETE_WINDOW", self.on_skip); self.center_dialog(parent)

    def _on_frame_configure(self, event=None):
        if self.canvas.winfo_exists(): self.canvas.itemconfig(self.canvas_frame, width=self.canvas.winfo_width())

    def _on_mousewheel(self, event):
        if not self.canvas.winfo_exists(): return
        y_scroll_info = self.canvas.yview(); can_scroll_up = y_scroll_info[0] > 0.0; can_scroll_down = y_scroll_info[1] < 1.0
        if sys.platform == "darwin": delta = event.delta
        else:
             if event.num == 5 or (hasattr(event, 'delta') and event.delta < 0): delta = -1
             elif event.num == 4 or (hasattr(event, 'delta') and event.delta > 0): delta = 1
             else: delta = 0
        if delta < 0:
            if can_scroll_down: self.canvas.yview_scroll(1, "units")
        elif delta > 0:
             if can_scroll_up: self.canvas.yview_scroll(-1, "units")

    def populate_candidates(self):
        for widget in self.scrollable_frame.winfo_children(): widget.destroy()
        if not PILLOW_AVAILABLE or not REQUESTS_AVAILABLE:
             warning_label = ttk.Label(self.scrollable_frame, text="Thumbnails require 'Pillow' and 'requests' libraries.", foreground="orange"); warning_label.pack(pady=10)
        if self.is_override:
            override_label = ttk.Label(self.scrollable_frame, text="Showing raw/unfiltered results:", foreground="orange", font=('Helvetica', 10, 'bold')); override_label.pack(pady=(5,10))
        for i, video in enumerate(self.candidates):
            item_frame = ttk.Frame(self.scrollable_frame, padding=5, relief=tk.RIDGE, borderwidth=1); item_frame.pack(pady=5, padx=5, fill=tk.X, expand=True)
            item_frame.columnconfigure(1, weight=1)
            thumb_label = ttk.Label(item_frame, text="[No Thumb]", width=int(THUMBNAIL_SIZE[0]/8), anchor=tk.CENTER); thumb_label.grid(row=0, column=0, rowspan=4, padx=5, pady=5, sticky=tk.NW)
            thumbnail_url = video.get('thumbnail')
            if PILLOW_AVAILABLE and REQUESTS_AVAILABLE and thumbnail_url:
                try:
                    photo = self.load_thumbnail(thumbnail_url, i)
                    if thumb_label.winfo_exists():
                        if photo: thumb_label.config(image=photo, text=""); thumb_label.image = photo
                except Exception as e: logger.error(f"Error during thumbnail display setup for {thumbnail_url}: {e}")
            title_label = ttk.Label(item_frame, text=video.get('title', 'N/A'), wraplength=450, font=('Helvetica', 10, 'bold')); title_label.grid(row=0, column=1, columnspan=2, padx=5, sticky=tk.NW)
            channel_label = ttk.Label(item_frame, text=f"Channel: {video.get('channel', 'N/A')}", wraplength=450); channel_label.grid(row=1, column=1, columnspan=2, padx=5, sticky=tk.NW)
            duration_val = video.get('duration'); duration_str = f"{int(duration_val // 60)}:{int(duration_val % 60):02d}" if duration_val else "N/A"
            views_val = video.get('views'); views_str = f"{views_val:,}" if views_val else "N/A"; score_val = video.get('score', 'N/A') if not self.is_override else 'N/A'
            info_text = f"Duration: {duration_str} | Views: {views_str}"
            if not self.is_override: info_text += f" | Score: {score_val}"
            info_label = ttk.Label(item_frame, text=info_text, wraplength=450); info_label.grid(row=2, column=1, columnspan=2, padx=5, sticky=tk.NW)
            video_url = video.get('url', '#'); link_label = ttk.Label(item_frame, text="Open Link", foreground="blue", cursor="hand2"); link_label.grid(row=3, column=1, padx=5, pady=5, sticky=tk.NW)
            if video_url != '#': link_label.bind("<Button-1>", lambda e, url=video_url: self.open_link(url)); ToolTip(link_label, f"Click to open {video_url} in browser")
            else: link_label.config(foreground="gray", cursor=""); ToolTip(link_label, "Video URL not available")
            current_video_id = video.get('id')
            select_button = ttk.Button(item_frame, text="Select This", command=lambda vid_id=current_video_id: self.on_select(vid_id))
            if current_video_id is None:
                select_button.config(state=tk.DISABLED)
                ToolTip(select_button, "Cannot select: Video ID is missing")
            select_button.grid(row=3, column=2, padx=5, pady=5, sticky=tk.NE)

    def load_thumbnail(self, url, index):
        if not url or not PILLOW_AVAILABLE or not REQUESTS_AVAILABLE: return None
        if index in self.thumbnail_cache: return self.thumbnail_cache[index]
        try:
            response = requests.get(url, stream=True, timeout=10); response.raise_for_status()
            img_data = response.content; img = Image.open(io.BytesIO(img_data))
            img.thumbnail(THUMBNAIL_SIZE, Image.Resampling.LANCZOS); photo = ImageTk.PhotoImage(img)
            self.thumbnail_cache[index] = photo; return photo
        except requests.exceptions.RequestException as e: logger.warning(f"Failed to fetch thumbnail {url}: {e}"); return None
        except UnidentifiedImageError: logger.warning(f"Pillow failed to identify image from {url} (invalid format?)."); return None
        except Exception as e: logger.error(f"Error loading thumbnail {url}: {e}", exc_info=False); return None

    def open_link(self, url):
        if not url or url == '#': logger.warning("Attempted to open an invalid URL."); return
        try: logger.info(f"Opening link: {url}"); webbrowser.open_new_tab(url)
        except Exception as e: logger.error(f"Failed to open link {url}: {e}");
        if self.winfo_exists(): messagebox.showerror("Error", f"Could not open link:\n{e}", parent=self)

    def _send_result_to_queue(self, result):
         try:
             if self.result_queue: logger.debug(f"ManualSelectDialog: Putting result ({result}) into result_queue..."); self.result_queue.put(result); logger.debug("ManualSelectDialog: Result put into queue.")
             else: logger.error("ManualSelectDialog: Result queue is not set.")
         except Exception as e: logger.error(f"ManualSelectDialog: Error putting result into queue: {e}")

    def on_select(self, video_id):
        if video_id is None:
             logger.error("on_select called with missing video ID.")
             if self.winfo_exists(): messagebox.showerror("Error", "Cannot select video: Missing video ID.", parent=self)
             return
        logger.info(f"ManualSelectDialog: User selected video ID: {video_id}"); self.result = video_id
        self._send_result_to_queue(self.result); self.thumbnail_cache.clear()
        if self.winfo_exists(): self.destroy()

    def on_skip(self):
        logger.info("ManualSelectDialog: User chose to skip."); self.result = None
        self._send_result_to_queue(self.result); self.thumbnail_cache.clear()
        if self.winfo_exists(): self.destroy()

    def center_dialog(self, parent):
        try:
            if not self.winfo_exists(): return; self.update_idletasks()
            if not parent.winfo_exists(): return
            parent_width = parent.winfo_width(); parent_height = parent.winfo_height()
            parent_x = parent.winfo_x(); parent_y = parent.winfo_y()
            dialog_width = self.winfo_width(); dialog_height = self.winfo_height()
            x = parent_x + (parent_width - dialog_width) // 2; y = parent_y + (parent_height - dialog_height) // 2
            x = max(0, x); y = max(0, y); self.geometry(f"+{x}+{y}")
        except tk.TclError as e: logger.warning(f"TclError centering dialog: {e}")

    # --- ADDED: Search by Filename Method ---
    def search_by_filename(self):
        """Performs a search using the base filename and updates the dialog."""
        if not self.filepath:
            logger.error("Filename search failed: Original filepath not available.")
            messagebox.showerror("Error", "Cannot perform filename search: Filepath missing.", parent=self)
            return

        base_filename = os.path.splitext(os.path.basename(self.filepath))[0]
        logger.info(f"Performing filename search within dialog: '{base_filename}'")
        # Show searching indicator? Maybe just freeze is acceptable here.
        self.update_idletasks() # Allow GUI to update briefly

        # Use perform_search synchronously
        # Need access to search result count - get from parent? Or hardcode? Let's get from parent.
        try:
            search_count = self.master.search_results_count.get() # Access parent's variable
        except Exception:
            search_count = DEFAULT_SEARCH_RESULTS_COUNT # Fallback
            logger.warning("Could not get search count from parent, using default.")

        new_videos = perform_search(base_filename, search_count)

        if new_videos is None:
            logger.error("Filename search failed (yt-dlp error).")
            messagebox.showerror("Search Error", f"Filename search failed for:\n'{base_filename}'\n\nCheck logs.", parent=self)
        elif not new_videos:
            logger.warning("Filename search yielded no results.")
            messagebox.showinfo("No Results", f"Filename search found no results for:\n'{base_filename}'", parent=self)
        else:
            logger.info(f"Filename search successful, updating candidates.")
            # Prepare candidates in the same format as _worker_filter_and_select returns
            new_candidates = []
            for video in new_videos:
                 vid_title_raw = video.get('title'); vid_title = vid_title_raw if isinstance(vid_title_raw, str) else ''
                 channel_raw = video.get('channel', video.get('uploader')); channel = channel_raw if isinstance(channel_raw, str) else ''
                 thumbnail_url = None; thumbnails = video.get('thumbnails')
                 if isinstance(thumbnails, list) and thumbnails:
                     thumbnail_url = thumbnails[-1].get('url')
                     if not thumbnail_url:
                          for thumb in reversed(thumbnails):
                              thumbnail_url = thumb.get('url')
                              if thumbnail_url: break
                 if not thumbnail_url: thumbnail_url = video.get('thumbnail')
                 new_candidates.append({'id': video.get('id'), 'title': vid_title, 'channel': channel,
                                        'duration': video.get('duration'),
                                        'url': video.get('webpage_url', f"https://www.youtube.com/watch?v={video.get('id')}" if video.get('id') else '#'),
                                        'score': 'N/A', # No score for raw results
                                        'views': video.get('view_count'), 'thumbnail': thumbnail_url})

            self.candidates = new_candidates
            self.is_override = True # Treat these as raw results
            self.thumbnail_cache.clear() # Clear old thumbnails
            self.title(f"Filename Search Results: {self.artist} - {self.title_str}") # Update title
            self.populate_candidates() # Refresh the list
            self.canvas.yview_moveto(0) # Scroll back to top

    # --- ADDED: Use URL Method ---
    def use_url(self):
        """Extracts video ID from the URL entry and sends it as the result."""
        url = self.url_entry_var.get().strip()
        if not url:
            messagebox.showwarning("Input Needed", "Please paste a YouTube URL first.", parent=self)
            return

        logger.info(f"Attempting to use provided URL: {url}")
        video_id = None
        # Try to extract video ID using regex (handles common formats)
        patterns = [
            r'(?:v=|\/)([0-9A-Za-z_-]{11}).*', # youtube.com/watch?v=... or /embed/...
            r'youtu\.be\/([0-9A-Za-z_-]{11})' # youtu.be/...
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                video_id = match.group(1)
                break

        if video_id:
            logger.info(f"Extracted Video ID: {video_id}")
            self.result = video_id
            self._send_result_to_queue(self.result)
            self.thumbnail_cache.clear()
            if self.winfo_exists(): self.destroy()
        else:
            logger.warning(f"Could not extract video ID from URL: {url}")
            messagebox.showerror("Invalid URL", "Could not extract a valid YouTube video ID from the provided URL.", parent=self)


# --- Main Application Class ---
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        missing_deps = []
        if not MUTAGEN_AVAILABLE: missing_deps.append("mutagen")
        if not REQUESTS_AVAILABLE: missing_deps.append("requests")
        if not PILLOW_AVAILABLE: missing_deps.append("Pillow")
        self.yt_dlp_ok = self.check_yt_dlp_exists()
        if not self.yt_dlp_ok: missing_deps.append("yt-dlp (not found in PATH)")
        if missing_deps:
             dep_str = ", ".join(missing_deps)
             messagebox.showerror("Missing Dependencies", f"Missing: {dep_str}.\nInstall/fix and restart.", parent=self)
             self.after(100, self.destroy); return
        self.title("Music Video Downloader GUI 🎬")
        self.minsize(width=700, height=550)
        self.columnconfigure(0, weight=1); self.rowconfigure(0, weight=1)
        self.music_dir = tk.StringVar(); self.output_dir = tk.StringVar()
        self.video_quality_format = tk.StringVar(value=DEFAULT_VIDEO_QUALITY_FORMAT)
        self.audio_quality_format = tk.StringVar(value=DEFAULT_AUDIO_QUALITY_FORMAT)
        self.search_results_count = tk.IntVar(value=DEFAULT_SEARCH_RESULTS_COUNT)
        self.download_delay = tk.IntVar(value=DEFAULT_DOWNLOAD_DELAY)
        self.interactive_mode = tk.BooleanVar(value=False)
        self.override_existing = tk.BooleanVar(value=False)
        self.no_trust_mode = tk.BooleanVar(value=False) # <-- Add No Trust Mode variable
        self.file_list_data = {} # Store file info: {filepath: {'item_id':..., 'status':..., 'rel_path':..., 'dl_full_path':...}}
        self.processing_thread = None
        self.stop_event = threading.Event()
        self.gui_queue = queue.Queue()
        self.manual_select_queue = queue.Queue()
        self.review_list = []
        self.current_review_item = None
        self.is_reviewing = False # Flag to prevent review re-entry
        self.configure_styles()
        self.create_widgets()
        self.setup_logging()
        self.after(100, self.process_gui_queue); self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def check_yt_dlp_exists(self):
        try:
            subprocess.run(['yt-dlp', '--version'], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=_get_startupinfo())
            logger.info("yt-dlp found successfully."); return True
        except FileNotFoundError: logger.critical("yt-dlp command not found in PATH."); return False
        except (subprocess.CalledProcessError, Exception) as e: logger.warning(f"Could not verify yt-dlp version: {e}"); return True

    # --- UPDATED: configure_styles for Dark Mode ---
    def configure_styles(self):
        """Configures ttk styles for a dark theme with purple accents."""
        style = ttk.Style(self)
        try:
            style.theme_use('clam')
            logger.debug("Using theme: clam")
        except tk.TclError:
            logger.warning("Clam theme not available, using default. Dark mode might not apply correctly.")
            # Basic fallback styles
            style.configure('.', background=BG_COLOR, foreground=FG_COLOR)
            style.configure('TButton', background=BUTTON_BG_COLOR, foreground=FG_COLOR)
            style.configure('TEntry', fieldbackground=ENTRY_BG_COLOR, foreground=FG_COLOR, insertcolor=FG_COLOR)
            style.configure('TLabel', background=BG_COLOR, foreground=FG_COLOR)
            style.configure('TCheckbutton', background=BG_COLOR, foreground=FG_COLOR, indicatorcolor=ACCENT_COLOR)
            style.configure('TSpinbox', fieldbackground=ENTRY_BG_COLOR, foreground=FG_COLOR, arrowcolor=FG_COLOR)
            style.configure('TLabelframe', background=BG_COLOR, bordercolor=FG_COLOR)
            style.configure('TLabelframe.Label', background=BG_COLOR, foreground=ACCENT_COLOR)
            style.configure('Treeview', background=ENTRY_BG_COLOR, fieldbackground=ENTRY_BG_COLOR, foreground=FG_COLOR)
            style.map('Treeview', background=[('selected', SELECT_BG_COLOR)], foreground=[('selected', FG_COLOR)])
            style.configure("Vertical.TScrollbar", background=BUTTON_BG_COLOR, troughcolor=BG_COLOR, bordercolor=BG_COLOR, arrowcolor=FG_COLOR)
            style.configure("Horizontal.TScrollbar", background=BUTTON_BG_COLOR, troughcolor=BG_COLOR, bordercolor=BG_COLOR, arrowcolor=FG_COLOR)
            style.configure("TProgressbar", troughcolor=ENTRY_BG_COLOR, bordercolor=ENTRY_BG_COLOR, background=ACCENT_COLOR)
            # Add Merge button style for fallback - REMOVED
            # style.configure('Merge.TButton', background=MERGE_BUTTON_BG, foreground=FG_COLOR)
            # style.map('Merge.TButton', background=[('active', MERGE_BUTTON_HOVER_BG)])
            return

        # --- Configure Clam Theme ---
        style.configure('.', background=BG_COLOR, foreground=FG_COLOR, fieldbackground=ENTRY_BG_COLOR, lightcolor=BG_COLOR, darkcolor=BG_COLOR, bordercolor="#555555")
        style.configure('TLabel', background=BG_COLOR, foreground=FG_COLOR)
        style.configure('TLabelframe', background=BG_COLOR, bordercolor=FG_COLOR, relief=tk.GROOVE)
        style.configure('TLabelframe.Label', background=BG_COLOR, foreground=ACCENT_COLOR, font=('Helvetica', 10, 'bold'))
        style.configure('TFrame', background=BG_COLOR)

        # Buttons
        style.configure('TButton', background=BUTTON_BG_COLOR, foreground=FG_COLOR, borderwidth=1, focusthickness=3, focuscolor=ACCENT_COLOR)
        style.map('TButton',
            background=[('pressed', ACCENT_COLOR), ('active', BUTTON_ACCENT_BG)],
            foreground=[('pressed', FG_COLOR), ('active', FG_COLOR)]
        )
        style.configure('Stop.TButton', foreground='#FFCCCC')
        style.map('Stop.TButton',
            background=[('pressed', '#AA0000'), ('active', '#DD0000')],
            foreground=[('pressed', FG_COLOR), ('active', FG_COLOR)]
        )
        # REMOVED Merge button style


        # Entry and Spinbox
        style.configure('TEntry', fieldbackground=ENTRY_BG_COLOR, foreground=FG_COLOR, insertcolor=FG_COLOR, borderwidth=1, relief=tk.FLAT)
        style.configure('TSpinbox', fieldbackground=ENTRY_BG_COLOR, foreground=FG_COLOR, arrowcolor=FG_COLOR, borderwidth=1, relief=tk.FLAT)
        style.map('TSpinbox', background=[('readonly', BG_COLOR)])

        # Checkbutton
        style.configure('TCheckbutton', background=BG_COLOR, foreground=FG_COLOR, indicatorcolor='black')
        style.map('TCheckbutton',
            indicatorbackground=[('selected', ACCENT_COLOR), ('active', BG_COLOR)],
            foreground=[('active', ACCENT_COLOR)]
            )

        # Treeview
        style.configure('Treeview', background=ENTRY_BG_COLOR, fieldbackground=ENTRY_BG_COLOR, foreground=FG_COLOR, rowheight=25)
        style.configure('Treeview.Heading', background=BUTTON_BG_COLOR, foreground=ACCENT_COLOR, relief=tk.FLAT, font=('Helvetica', 10, 'bold'))
        style.map('Treeview.Heading', relief=[('active','groove'),('pressed','sunken')])
        style.map('Treeview', background=[('selected', SELECT_BG_COLOR)], foreground=[('selected', FG_COLOR)])

        # Scrollbars
        style.configure("Vertical.TScrollbar", background=BUTTON_BG_COLOR, troughcolor=BG_COLOR, bordercolor=BG_COLOR, arrowcolor=FG_COLOR)
        style.map("Vertical.TScrollbar", background=[('active', BUTTON_HOVER_BG)], arrowcolor=[('pressed', ACCENT_COLOR)])
        style.configure("Horizontal.TScrollbar", background=BUTTON_BG_COLOR, troughcolor=BG_COLOR, bordercolor=BG_COLOR, arrowcolor=FG_COLOR)
        style.map("Horizontal.TScrollbar", background=[('active', BUTTON_HOVER_BG)], arrowcolor=[('pressed', ACCENT_COLOR)])

        # Progressbar
        style.configure("TProgressbar", troughcolor=ENTRY_BG_COLOR, bordercolor=ENTRY_BG_COLOR, background=ACCENT_COLOR, lightcolor=ACCENT_COLOR, darkcolor=ACCENT_COLOR)

        # Apply background to main window
        self.configure(background=BG_COLOR)

        # Treeview Status Colors (using tags)
        style.configure("NeedsReview.Treeview", foreground="#FFA500") # Orange
        style.configure("Reviewing.Treeview", foreground="#5DADE2") # Lighter Blue
        style.configure("Queued.Treeview", foreground="#AAAAAA") # Lighter Grey
        style.configure("Processing.Treeview", foreground="#5DADE2") # Lighter Blue
        style.configure("Complete.Treeview", foreground="#58D68D") # Green
        style.configure("Failed.Treeview", foreground="#EC7063") # Red
        style.configure("Skipped.Treeview", foreground="#F5B041") # Lighter Orange
        style.configure("Exists.Treeview", foreground="#AF7AC5") # Lighter Purple
        style.configure("Error.Treeview", foreground="#F1948A", font=('Helvetica', 9, 'bold')) # Light Red/Pink
        # style.configure("Merged.Treeview", foreground="#45B39D") # No longer needed


    def create_widgets(self):
        main_frame = ttk.Frame(self, padding="10", style='TFrame'); main_frame.grid(row=0, column=0, sticky=tk.NSEW)
        main_frame.columnconfigure(0, weight=1); main_frame.rowconfigure(2, weight=1)

        dir_frame = ttk.LabelFrame(main_frame, text="Directories", padding="10", style='TLabelframe'); dir_frame.grid(row=0, column=0, sticky=tk.EW, pady=(0, 5))
        dir_frame.columnconfigure(1, weight=1)

        ttk.Label(dir_frame, text="Music Folder:", style='TLabel').grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        ttk.Entry(dir_frame, textvariable=self.music_dir, width=60, style='TEntry').grid(row=0, column=1, padx=5, pady=5, sticky=tk.EW)
        ttk.Button(dir_frame, text="Browse...", command=self.browse_music_dir, style='TButton').grid(row=0, column=2, padx=5, pady=5)
        ttk.Label(dir_frame, text="Output Folder:", style='TLabel').grid(row=1, column=0, padx=5, pady=5, sticky=tk.W)
        ttk.Entry(dir_frame, textvariable=self.output_dir, width=60, style='TEntry').grid(row=1, column=1, padx=5, pady=5, sticky=tk.EW)
        ttk.Button(dir_frame, text="Browse...", command=self.browse_output_dir, style='TButton').grid(row=1, column=2, padx=5, pady=5)

        options_frame = ttk.LabelFrame(main_frame, text="Options", padding="10", style='TLabelframe'); options_frame.grid(row=1, column=0, sticky=tk.EW, pady=5)
        options_frame.columnconfigure(1, weight=1)

        vqf_label = ttk.Label(options_frame, text="Video Format:", style='TLabel'); vqf_label.grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        vqf_entry = ttk.Entry(options_frame, textvariable=self.video_quality_format, width=50, style='TEntry'); vqf_entry.grid(row=0, column=1, padx=5, pady=5, sticky=tk.EW)
        ToolTip(vqf_label, "yt-dlp video format selector."); ToolTip(vqf_entry, "yt-dlp video format selector.")
        aqf_label = ttk.Label(options_frame, text="Audio Format:", style='TLabel'); aqf_label.grid(row=1, column=0, padx=5, pady=5, sticky=tk.W)
        aqf_entry = ttk.Entry(options_frame, textvariable=self.audio_quality_format, width=50, style='TEntry'); aqf_entry.grid(row=1, column=1, padx=5, pady=5, sticky=tk.EW)
        ToolTip(aqf_label, "yt-dlp audio format selector."); ToolTip(aqf_entry, "yt-dlp audio format selector.")
        sr_label = ttk.Label(options_frame, text="Search Results:", style='TLabel'); sr_label.grid(row=2, column=0, padx=5, pady=5, sticky=tk.W)
        vcmd = (self.register(self._validate_int), '%P'); sr_spinbox = ttk.Spinbox(options_frame, from_=1, to=20, textvariable=self.search_results_count, width=5, validate='key', validatecommand=vcmd, style='TSpinbox'); sr_spinbox.grid(row=2, column=1, padx=5, pady=5, sticky=tk.W)
        ToolTip(sr_label, "How many YouTube search results to fetch."); ToolTip(sr_spinbox, "How many YouTube search results to fetch.")
        dd_label = ttk.Label(options_frame, text="Download Delay (s):", style='TLabel'); dd_label.grid(row=3, column=0, padx=5, pady=5, sticky=tk.W)
        dd_spinbox = ttk.Spinbox(options_frame, from_=0, to=60, textvariable=self.download_delay, width=5, validate='key', validatecommand=vcmd, style='TSpinbox'); dd_spinbox.grid(row=3, column=1, padx=5, pady=5, sticky=tk.W)
        ToolTip(dd_label, "Seconds to wait between downloads."); ToolTip(dd_spinbox, "Seconds to wait between downloads.")

        # --- Add Mode and Override Checkboxes ---
        mode_frame = ttk.Frame(options_frame, style='TFrame') # Frame to hold mode checkboxes
        mode_frame.grid(row=4, column=0, columnspan=2, sticky=tk.W)

        interactive_check = ttk.Checkbutton(mode_frame, text="Interactive Mode", variable=self.interactive_mode, style='TCheckbutton')
        interactive_check.pack(side=tk.LEFT, padx=5, pady=5)
        ToolTip(interactive_check, "Pause processing immediately for manual input.")

        override_check = ttk.Checkbutton(mode_frame, text="Override Existing", variable=self.override_existing, style='TCheckbutton')
        override_check.pack(side=tk.LEFT, padx=5, pady=5)
        ToolTip(override_check, "Re-process files even if marked as 'Exists'.")

        # --- Add No Trust Mode Checkbox ---
        no_trust_check = ttk.Checkbutton(mode_frame, text="No Trust Mode", variable=self.no_trust_mode, style='TCheckbutton')
        no_trust_check.pack(side=tk.LEFT, padx=5, pady=5)
        ToolTip(no_trust_check, "Force manual selection for every file (ignores auto-select).")
        # --- End Add ---

        center_frame = ttk.Frame(main_frame, style='TFrame'); center_frame.grid(row=2, column=0, sticky=tk.NSEW, pady=5)
        center_frame.columnconfigure(0, weight=1); center_frame.columnconfigure(1, weight=2); center_frame.rowconfigure(0, weight=1)

        file_list_frame = ttk.LabelFrame(center_frame, text="Files to Process", padding="5", style='TLabelframe'); file_list_frame.grid(row=0, column=0, sticky=tk.NSEW, padx=(0, 5))
        file_list_frame.rowconfigure(0, weight=1); file_list_frame.columnconfigure(0, weight=1)

        self.file_tree = ttk.Treeview(file_list_frame, columns=("Status", "File"), show='headings', selectmode='none', style='Treeview'); self.file_tree.heading("Status", text="Status"); self.file_tree.heading("File", text="File")
        self.file_tree.column("Status", width=120, anchor=tk.W, stretch=False); self.file_tree.column("File", width=300, anchor=tk.W)
        file_tree_vsb = ttk.Scrollbar(file_list_frame, orient="vertical", command=self.file_tree.yview, style="Vertical.TScrollbar"); file_tree_hsb = ttk.Scrollbar(file_list_frame, orient="horizontal", command=self.file_tree.xview, style="Horizontal.TScrollbar")
        self.file_tree.configure(yscrollcommand=file_tree_vsb.set, xscrollcommand=file_tree_hsb.set); self.file_tree.grid(row=0, column=0, sticky=tk.NSEW); file_tree_vsb.grid(row=0, column=1, sticky=tk.NS); file_tree_hsb.grid(row=1, column=0, sticky=tk.EW)

        log_frame = ttk.LabelFrame(center_frame, text="Logs", padding="5", style='TLabelframe'); log_frame.grid(row=0, column=1, sticky=tk.NSEW, padx=(5, 0))
        log_frame.rowconfigure(0, weight=1); log_frame.columnconfigure(0, weight=1)

        self.log_text = scrolledtext.ScrolledText(log_frame, state='disabled', wrap=tk.WORD, height=10, font=("Consolas", 9),
                                                  background=ENTRY_BG_COLOR, foreground=FG_COLOR, insertbackground=FG_COLOR, relief=tk.FLAT, borderwidth=1);
        self.log_text.grid(row=0, column=0, sticky=tk.NSEW)

        bottom_frame = ttk.Frame(main_frame, padding="5", style='TFrame'); bottom_frame.grid(row=3, column=0, sticky=tk.EW); bottom_frame.columnconfigure(0, weight=1)

        progress_frame = ttk.Frame(bottom_frame, style='TFrame'); progress_frame.grid(row=0, column=0, sticky=tk.EW, pady=(0, 5)); progress_frame.columnconfigure(1, weight=1)
        ttk.Label(progress_frame, text="Overall:", style='TLabel').grid(row=0, column=0, padx=5, sticky=tk.W); self.overall_progress = ttk.Progressbar(progress_frame, orient='horizontal', mode='determinate', style="TProgressbar"); self.overall_progress.grid(row=0, column=1, padx=5, sticky=tk.EW); self.overall_progress_label = ttk.Label(progress_frame, text="0/0", style='TLabel'); self.overall_progress_label.grid(row=0, column=2, padx=5, sticky=tk.E)
        ttk.Label(progress_frame, text="Current File:", style='TLabel').grid(row=1, column=0, padx=5, sticky=tk.W); self.file_progress = ttk.Progressbar(progress_frame, orient='horizontal', mode='determinate', style="TProgressbar"); self.file_progress.grid(row=1, column=1, padx=5, sticky=tk.EW); self.file_progress_label = ttk.Label(progress_frame, text="Idle", style='TLabel'); self.file_progress_label.grid(row=1, column=2, padx=5, sticky=tk.E)

        # --- Button Frame ---
        self.button_frame = ttk.Frame(bottom_frame, style='TFrame'); self.button_frame.grid(row=1, column=0, pady=(5, 0))

        self.start_button = ttk.Button(self.button_frame, text="Start Processing", command=self.start_processing, style='TButton'); self.start_button.pack(side=tk.LEFT, padx=5)
        self.review_button = ttk.Button(self.button_frame, text="Review Pending (0)", command=self.start_review_phase, state=tk.DISABLED, style='TButton'); self.review_button.pack(side=tk.LEFT, padx=5)
        ToolTip(self.review_button, "Process files that need manual input (search/selection).")
        self.stop_button = ttk.Button(self.button_frame, text="Stop", command=self.stop_processing, state=tk.DISABLED, style='Stop.TButton'); self.stop_button.pack(side=tk.LEFT, padx=5)

        # --- Merge Button Removed ---
        # self.merge_button = ttk.Button(self.button_frame, text="Merge Videos", command=self.start_merge, style='Merge.TButton')
        # ToolTip(self.merge_button, "Move downloaded videos into original music folders.")

        start_tooltip = ""; can_start = MUTAGEN_AVAILABLE and REQUESTS_AVAILABLE and PILLOW_AVAILABLE and self.yt_dlp_ok
        if not can_start:
            self.start_button.config(state=tk.DISABLED); missing = []
            if not MUTAGEN_AVAILABLE: missing.append('mutagen')
            if not REQUESTS_AVAILABLE: missing.append('requests')
            if not PILLOW_AVAILABLE: missing.append('Pillow')
            if not self.yt_dlp_ok: missing.append('yt-dlp (not found in PATH)')
            start_tooltip = f"Disabled. Missing: {', '.join(missing)}"; ToolTip(self.start_button, start_tooltip)

    def _validate_int(self, P):
        if P == "" or P.isdigit(): return True
        else: return False

    def setup_logging(self):
        if hasattr(self, 'log_text') and self.log_text.winfo_exists():
            gui_handler = GuiLogHandler(self.log_text); gui_handler.setFormatter(log_formatter)
            logger.addHandler(gui_handler); logger.info("GUI Initialized. Logging started.")
            # Apply dark mode to log text here too, after it exists
            try: self.log_text.config(background=ENTRY_BG_COLOR, foreground=FG_COLOR, insertbackground=FG_COLOR)
            except tk.TclError: pass
        else: logger.error("Log text widget not available during logging setup.")

    def browse_music_dir(self):
        directory = filedialog.askdirectory(title="Select Music Folder")
        if directory: self.music_dir.set(directory); self.scan_music_files()

    def browse_output_dir(self):
        directory = filedialog.askdirectory(title="Select Output Folder")
        if directory: self.output_dir.set(directory)

    def scan_music_files(self):
        music_dir = self.music_dir.get()
        if not music_dir or not os.path.isdir(music_dir): return
        if hasattr(self, 'file_tree') and self.file_tree.winfo_exists():
            for item in self.file_tree.get_children(): self.file_tree.delete(item)
        self.file_list_data.clear(); self.review_list.clear()
        if hasattr(self, 'overall_progress'): self.overall_progress['value'] = 0; self.overall_progress['maximum'] = 1
        if hasattr(self, 'review_button'): self.review_button.config(text="Review Pending (0)", state=tk.DISABLED)
        self._show_standard_buttons() # Ensure standard buttons are shown on new scan
        # self._hide_merge_button() # No merge button
        logger.info(f"Scanning music directory: {music_dir}"); files_found = []
        supported_extensions = ('.mp3', '.flac', '.wav', '.ogg', '.m4a', '.aac')
        try:
            for root, _, files in os.walk(music_dir):
                for filename in files:
                    if self.stop_event.is_set(): logger.info("Scan stopped by user."); return
                    if filename.lower().endswith(supported_extensions):
                        try: filepath = os.path.join(root, filename); files_found.append(filepath)
                        except OSError as e: logger.warning(f"Could not access file during scan: {filepath} - {e}")
                        except Exception as e: logger.error(f"Unexpected error processing file during scan: {filepath} - {e}")
            files_found.sort()
            if not self.winfo_exists() or not hasattr(self, 'file_tree') or not self.file_tree.winfo_exists():
                 logger.warning("GUI closed during file scan."); return
            if not files_found:
                 logger.warning("No compatible audio files found."); messagebox.showwarning("No Files", f"No compatible audio files found.", parent=self); return
            self.overall_progress['maximum'] = len(files_found); self.update_overall_progress(0, len(files_found))
            for filepath in files_found:
                 if self.stop_event.is_set(): break
                 if not self.file_tree.winfo_exists(): break
                 try: rel_path = os.path.relpath(os.path.normpath(filepath), os.path.normpath(music_dir))
                 except ValueError: rel_path = os.path.basename(filepath); logger.warning(f"Could not get relative path for {filepath}. Using basename.")
                 item_id = self.file_tree.insert("", tk.END, values=(STATUS_QUEUED, rel_path), tags=('Queued',))
                 # Initialize file data dictionary (removed merge-specific keys)
                 self.file_list_data[filepath] = {'item_id': item_id, 'status': STATUS_QUEUED, 'rel_path': rel_path, 'dl_full_path': None}
            logger.info(f"Found {len(files_found)} audio files.")
        except Exception as e:
            logger.error(f"Error scanning directory {music_dir}: {e}", exc_info=True)
            if self.winfo_exists(): messagebox.showerror("Scan Error", f"An error occurred while scanning:\n{e}", parent=self)

    def update_file_status(self, filepath, status, message=""):
        if not self.winfo_exists() or not hasattr(self, 'file_tree') or not self.file_tree.winfo_exists(): return
        if filepath in self.file_list_data:
            item_id = self.file_list_data[filepath]['item_id']
            rel_path = self.file_list_data[filepath].get('rel_path', os.path.basename(filepath))
            self.file_list_data[filepath]['status'] = status
            tag = "Queued";
            if status in [STATUS_PROCESSING, STATUS_SEARCHING, STATUS_FILTERING, STATUS_DOWNLOADING]: tag = "Processing"
            elif status == STATUS_COMPLETE: tag = "Complete"
            elif status.startswith("❌") or status == STATUS_ERROR: tag = "Failed"
            elif status.startswith("⏭️") or status == STATUS_SKIPPED_MANUAL: tag = "Skipped"
            elif status == STATUS_EXISTS: tag = "Exists"
            elif status == STATUS_NEEDS_REVIEW: tag = "NeedsReview"
            elif status == STATUS_REVIEWING: tag = "Reviewing"
            # elif status == STATUS_MERGED: tag = "Merged" # No longer needed
            if self.file_tree.exists(item_id):
                try: self.file_tree.item(item_id, values=(status, rel_path), tags=(tag,)); self.file_tree.see(item_id)
                except tk.TclError as e: logger.warning(f"TclError updating tree item {item_id}: {e}")
            else: logger.warning(f"Attempted to update status for non-existent tree item: {item_id} ({filepath})")
            if hasattr(self, 'file_progress_label') and self.file_progress_label.winfo_exists():
                current_file_display = os.path.basename(filepath)
                self.file_progress_label.config(text=f"{current_file_display}: {message if message else status}")
                if hasattr(self, 'file_progress') and self.file_progress.winfo_exists():
                    if status == STATUS_DOWNLOADING: self.file_progress.config(mode='indeterminate'); self.file_progress.start(10)
                    else: self.file_progress.stop(); self.file_progress.config(mode='determinate', value=0)

    def update_overall_progress(self, current, total):
        if not hasattr(self, 'overall_progress') or not self.overall_progress.winfo_exists(): return
        if not hasattr(self, 'overall_progress_label') or not self.overall_progress_label.winfo_exists(): return
        if total > 0: self.overall_progress['value'] = current; self.overall_progress['maximum'] = total; self.overall_progress_label.config(text=f"{current}/{total}")
        else: self.overall_progress['value'] = 0; self.overall_progress['maximum'] = 1; self.overall_progress_label.config(text="0/0")

    def process_gui_queue(self):
        """Processes messages from the worker thread queue."""
        try:
            while True:
                message = self.gui_queue.get_nowait()
                if not self.winfo_exists(): break
                msg_type = message.get('type'); data = message.get('data')

                if msg_type == 'status_update':
                    self.update_file_status(data['filepath'], data['status'], data.get('message', ''))
                elif msg_type == 'progress_update':
                    self.update_overall_progress(data['current'], data['total'])
                elif msg_type == 'review_needed':
                     logger.info(f"File queued for review ({data.get('reason', 'N/A')}): {data.get('filepath')}")
                     self.review_list.append(data)
                     self.update_file_status(data['filepath'], STATUS_NEEDS_REVIEW)
                     # Enable review button if not already reviewing
                     if not self.is_reviewing and hasattr(self, 'review_button') and self.review_button.winfo_exists():
                          self.review_button.config(text=f"Review Pending ({len(self.review_list)})", state=tk.NORMAL)
                elif msg_type == 'ask_manual_select':
                     # Pass filepath to the handler for interactive mode
                     if self.winfo_exists(): self.handle_manual_selection(data['candidates'], data['artist'], data['title'], data.get('filepath'), data.get('is_override', False))
                elif msg_type == 'ask_manual_search':
                     # Pass filepath to the handler for interactive mode
                     if self.winfo_exists(): self.handle_manual_search(data['artist'], data['title'], data.get('filepath'))
                # --- UPDATED: Store full path ---
                elif msg_type == 'store_merge_info': # Renamed for clarity, though merge is gone
                     filepath = data.get('filepath')
                     if filepath and filepath in self.file_list_data:
                         self.file_list_data[filepath]['dl_full_path'] = data.get('downloaded_full_path') # Store full path
                         logger.debug(f"Stored download path info for {filepath}: {data.get('downloaded_full_path')}")
                     else:
                         logger.warning(f"Could not store download path info for invalid filepath: {filepath}")
                # --- END UPDATE ---
                elif msg_type == 'initial_pass_complete':
                     self.on_initial_pass_finished(data.get('error'))
                elif msg_type == 'error_message':
                    if self.winfo_exists(): messagebox.showerror("Error", data['message'], parent=self)

        except queue.Empty: pass
        except Exception as e: logger.error(f"Error processing GUI queue: {e}", exc_info=True)
        finally:
            if self.winfo_exists(): self.after(100, self.process_gui_queue)

    # Modified handle_manual_selection to accept filepath
    def handle_manual_selection(self, candidates, artist, title, filepath, is_override=False):
        """Shows the manual selection dialog (used only in interactive mode)."""
        if not PILLOW_AVAILABLE or not REQUESTS_AVAILABLE:
            logger.warning("Pillow/Requests missing, thumbnails disabled.")
        # Pass the manual_select_queue and filepath for interactive mode
        dialog = ManualSelectDialog(self, self.manual_select_queue, candidates, artist, title, filepath, is_override)

    # Modified handle_manual_search to accept filepath
    def handle_manual_search(self, artist, title, filepath):
         """Prompts the user for a manual search query (used only in interactive mode)."""
         logger.info("Asking user for manual search query.")
         prompt = f"Automatic searches failed for:\n'{artist} - {title}'\n\nEnter your own search query (or leave blank to search filename):"
         user_query = simpledialog.askstring("Manual Search", prompt, parent=self)
         if user_query is not None:
              user_query = user_query.strip()
              if user_query:
                   logger.info(f"User provided manual search query: '{user_query}'")
                   self.manual_select_queue.put(user_query)
              else:
                   logger.info("User left manual search blank, requesting filename search.")
                   self.manual_select_queue.put("__FILENAME_SEARCH__") # Send special signal
         else:
              logger.info("User cancelled manual search.")
              self.manual_select_queue.put(None) # Send None to indicate skip/cancel

    # Modified process_single_review_item to pass filepath to dialog
    def process_single_review_item(self, review_item):
        """Processes one item from the review list (called by start_review_phase)."""
        self.current_review_item = review_item
        filepath = review_item['filepath']
        reason = review_item['reason']
        artist = review_item['artist']
        title = review_item['title']

        self.update_file_status(filepath, STATUS_REVIEWING)
        self.update()

        selected_video_id = None
        final_status = STATUS_SKIPPED_MANUAL
        downloaded_file_path_for_merge = None # Store full path if downloaded in review

        try:
            temp_result_queue = queue.Queue()

            if reason == 'select' or reason == 'override':
                logger.info(f"Review: Showing manual selection for {title} (Override: {reason=='override'})")
                # Pass filepath to the dialog
                dialog = ManualSelectDialog(self, temp_result_queue, review_item['candidates'], artist, title, filepath, is_override=(reason=='override'))
                self.wait_window(dialog)
                try: selected_video_id = temp_result_queue.get_nowait()
                except queue.Empty: selected_video_id = dialog.result
                logger.info(f"Review: Manual selection result: {selected_video_id}")

            elif reason == 'search':
                logger.info(f"Review: Showing manual search for {title}")
                prompt = f"Automatic searches failed for:\n'{artist} - {title}'\n\nEnter your own search query (or leave blank to search filename):"
                manual_query_result = simpledialog.askstring("Manual Search", prompt, parent=self)

                manual_query = None
                if manual_query_result is not None:
                    manual_query_result = manual_query_result.strip()
                    if manual_query_result: manual_query = manual_query_result
                    else: manual_query = os.path.splitext(os.path.basename(filepath))[0]; logger.info(f"Review: Using filename for manual search: '{manual_query}'")
                else: logger.info("Review: User cancelled manual search.")

                if manual_query:
                    logger.info(f"Review: Performing manual search: '{manual_query}'")
                    self.update_file_status(filepath, STATUS_SEARCHING, "Manual search...")
                    self.update()
                    videos_manual = perform_search(manual_query, self.search_results_count.get())

                    if videos_manual:
                        logger.info("Review: Manual search found results. Showing override selection.")
                        self.update_file_status(filepath, STATUS_FILTERING, "Override selection?")
                        self.update()
                        # Pass filepath to the dialog
                        dialog = ManualSelectDialog(self, temp_result_queue, videos_manual, artist, title, filepath, is_override=True)
                        self.wait_window(dialog)
                        try: selected_video_id = temp_result_queue.get_nowait()
                        except queue.Empty: selected_video_id = dialog.result
                        logger.info(f"Review: Manual override dialog result: {selected_video_id}")
                    else: logger.warning("Review: Manual search yielded no results."); final_status = STATUS_FAILED_SEARCH

            # --- Process result ---
            if selected_video_id:
                logger.info(f"Review: Proceeding with download for {title} (ID: {selected_video_id})")
                self.update_file_status(filepath, STATUS_DOWNLOADING)
                self.update()
                # --- Use single output directory ---
                current_output_dir = self.output_dir.get()
                if not os.path.exists(current_output_dir): os.makedirs(current_output_dir)
                # --- End change ---

                video_pref = self.video_quality_format.get().strip(); audio_pref = self.audio_quality_format.get().strip()
                if video_pref and audio_pref: final_quality_format = f"{video_pref}+{audio_pref}/{video_pref}/{audio_pref}/{DEFAULT_COMBINED_FALLBACK_FORMAT}"
                elif video_pref: final_quality_format = f"{video_pref}/{DEFAULT_COMBINED_FALLBACK_FORMAT}"
                elif audio_pref: final_quality_format = f"{DEFAULT_VIDEO_QUALITY_FORMAT}+{audio_pref}/{audio_pref}/{DEFAULT_COMBINED_FALLBACK_FORMAT}"
                else: final_quality_format = DEFAULT_COMBINED_FALLBACK_FORMAT

                sanitized_artist = _worker_sanitize_filename(artist); sanitized_title = _worker_sanitize_filename(title)
                # --- UPDATED: Get full path from perform_download ---
                download_success, downloaded_file_path_for_merge = perform_download(selected_video_id, sanitized_artist, sanitized_title, current_output_dir, final_quality_format, self.gui_queue)
                # --- END UPDATE ---
                final_status = STATUS_COMPLETE if download_success else STATUS_FAILED_DOWNLOAD
                # Store info (not needed for merge, but kept for potential future use)
                if download_success and filepath in self.file_list_data:
                    self.file_list_data[filepath]['dl_full_path'] = downloaded_file_path_for_merge # Store full path
                    logger.debug(f"Stored download path info (review) for {filepath}: {downloaded_file_path_for_merge}")

            elif selected_video_id is None and final_status == STATUS_SKIPPED_MANUAL:
                 logger.info(f"Review: User skipped {title}")

        except Exception as e:
            logger.error(f"Error during review processing for {filepath}: {e}", exc_info=True)
            final_status = STATUS_ERROR
        finally:
            self.update_file_status(filepath, final_status)
            self.current_review_item = None


    # Modified start_review_phase to use self.after for non-blocking GUI
    def start_review_phase(self):
        """Starts processing items in the review list sequentially using self.after()"""
        if self.is_reviewing: # Prevent re-entry
            logger.warning("Review phase already running.")
            return

        if not self.review_list:
            logger.info("Review button clicked, but no items to review.")
            messagebox.showinfo("Review Complete", "No items needed manual review.", parent=self)
            return

        self.is_reviewing = True # Set flag
        logger.info(f"Starting review phase for {len(self.review_list)} items.")
        # Disable buttons
        if hasattr(self, 'review_button') and self.review_button.winfo_exists():
             self.review_button.config(state=tk.DISABLED, text=f"Reviewing... ({len(self.review_list)} left)")
        if hasattr(self, 'start_button') and self.start_button.winfo_exists():
             self.start_button.config(state=tk.DISABLED) # Keep start disabled during review
        self.update()

        # Schedule the first item processing
        self.after(50, self._process_next_review_item) # Use helper to manage loop

    def _process_next_review_item(self):
        """Processes one review item and schedules the next one."""
        if not self.is_reviewing: # Check if stop was requested
             logger.info("Review phase aborted.")
             # Re-enable buttons if appropriate (e.g., based on worker thread state)
             self._update_button_states_after_processing()
             return

        if not self.review_list: # Check if list is empty
            self.is_reviewing = False # Clear flag
            logger.info("Review phase complete.")
            if hasattr(self, 'review_button') and self.review_button.winfo_exists():
                 self.review_button.config(text="Review Pending (0)", state=tk.DISABLED)
            if self.winfo_exists():
                 messagebox.showinfo("Review Complete", "Finished processing all items needing review.", parent=self)
            # --- No Merge Button ---
            self._update_button_states_after_processing(show_merge_option=False) # Never show merge now
            return

        # Process the next item
        review_item = self.review_list.pop(0)
        if hasattr(self, 'review_button') and self.review_button.winfo_exists(): # Update count
             self.review_button.config(text=f"Reviewing... ({len(self.review_list)} left)")

        self.process_single_review_item(review_item)

        # Schedule the next iteration ONLY if not stopped
        if self.is_reviewing:
            self.after(50, self._process_next_review_item) # Call this method again


    # Renamed from on_processing_finished
    def on_initial_pass_finished(self, error=None):
        """Called when the initial worker thread pass finishes."""
        # Keep stop button disabled
        if hasattr(self, 'stop_button') and self.stop_button.winfo_exists():
             self.stop_button.config(state=tk.DISABLED, text="Stop")

        self.processing_thread = None # Mark thread as finished

        if hasattr(self, 'file_progress') and self.file_progress.winfo_exists():
            self.file_progress.stop(); self.file_progress.config(value=0)
        if hasattr(self, 'file_progress_label') and self.file_progress_label.winfo_exists():
            self.file_progress_label.config(text="Idle")

        enable_review = bool(self.review_list)
        # show_merge = False # Merge button removed

        if self.stop_event.is_set():
             logger.info("Initial processing stopped by user.")
             if self.winfo_exists(): messagebox.showinfo("Stopped", "Initial processing was stopped.", parent=self)
        elif error:
             logger.error(f"Initial processing finished with error: {error}")
             if self.winfo_exists(): messagebox.showerror("Error", f"Initial processing finished with an error:\n{error}", parent=self)
        else: # Initial pass completed without error or stop
             logger.info("Initial processing pass finished successfully.")
             if not enable_review and not self.is_reviewing: # Only show "Complete" if no review needed AND not currently reviewing
                  logger.info("No items need review. Processing complete.")
                  if self.winfo_exists(): messagebox.showinfo("Complete", "Processing finished!", parent=self)
                  # show_merge = True # No merge button
             # If review is needed, the message is shown when review button is enabled later

        # Update buttons after initial pass is done
        self._update_button_states_after_processing(show_merge_option=False) # Never show merge


    def _update_button_states_after_processing(self, show_merge_option=False): # show_merge_option kept for signature consistency but ignored
        """Updates Start/Review button states based on current conditions."""
        is_worker_running = self.processing_thread and self.processing_thread.is_alive()
        can_start_deps = MUTAGEN_AVAILABLE and REQUESTS_AVAILABLE and PILLOW_AVAILABLE and self.yt_dlp_ok
        # can_merge = show_merge_option and not self.is_reviewing and not is_worker_running # No longer needed

        # --- Simplified: Only show standard buttons ---
        self._show_standard_buttons()
        # self._hide_merge_button() # No merge button

        # Enable Start only if worker AND review are not running, and deps are met
        start_state = tk.NORMAL if (not is_worker_running and not self.is_reviewing and can_start_deps) else tk.DISABLED
        if hasattr(self, 'start_button') and self.start_button.winfo_exists():
            self.start_button.config(state=start_state)

        # Enable Review only if items exist AND review is not currently running
        review_state = tk.NORMAL if self.review_list and not self.is_reviewing else tk.DISABLED
        if hasattr(self, 'review_button') and self.review_button.winfo_exists():
             current_text = self.review_button.cget("text")
             if not self.is_reviewing or "Pending" in current_text:
                 self.review_button.config(text=f"Review Pending ({len(self.review_list)})", state=review_state)
             else:
                 self.review_button.config(state=review_state)

        # Stop button state managed elsewhere


    def _show_standard_buttons(self):
        """Shows Start, Review, Stop buttons."""
        if hasattr(self, 'start_button'): self.start_button.pack(side=tk.LEFT, padx=5)
        if hasattr(self, 'review_button'): self.review_button.pack(side=tk.LEFT, padx=5)
        if hasattr(self, 'stop_button'): self.stop_button.pack(side=tk.LEFT, padx=5)

    def _hide_standard_buttons(self):
        """Hides Start, Review, Stop buttons."""
        if hasattr(self, 'start_button'): self.start_button.pack_forget()
        if hasattr(self, 'review_button'): self.review_button.pack_forget()
        if hasattr(self, 'stop_button'): self.stop_button.pack_forget()

    # --- REMOVED Merge Button Functions ---
    # def _show_merge_button(self): ...
    # def _hide_merge_button(self): ...
    # def start_merge(self): ...


    def start_processing(self):
        """Validates inputs and starts the background processing thread."""
        can_start = MUTAGEN_AVAILABLE and REQUESTS_AVAILABLE and PILLOW_AVAILABLE and self.yt_dlp_ok
        if not can_start:
             missing = [];
             if not MUTAGEN_AVAILABLE: missing.append('mutagen')
             if not REQUESTS_AVAILABLE: missing.append('requests')
             if not PILLOW_AVAILABLE: missing.append('Pillow')
             if not self.yt_dlp_ok: missing.append('yt-dlp')
             messagebox.showerror("Missing Dependencies", f"Cannot start. Missing: {', '.join(missing)}.", parent=self); return
        music_dir = self.music_dir.get(); output_dir = self.output_dir.get()
        if not music_dir or not os.path.isdir(music_dir): messagebox.showerror("Input Error", "Select valid music directory.", parent=self); return
        if not output_dir: messagebox.showerror("Input Error", "Select output directory.", parent=self); return
        try:
            if not os.path.exists(output_dir): os.makedirs(output_dir); logger.info(f"Created output directory: {output_dir}")
            elif not os.path.isdir(output_dir): messagebox.showerror("Output Error", f"Output path exists but is not a directory.", parent=self); return
        except OSError as e: messagebox.showerror("Output Error", f"Could not create/access output directory:\n{e}", parent=self); return
        if not self.file_list_data:
             messagebox.showinfo("Scan Needed", "Select music directory first.", parent=self); self.scan_music_files()
             if not self.file_list_data: return
        video_pref = self.video_quality_format.get().strip(); audio_pref = self.audio_quality_format.get().strip(); final_quality_format = ""
        if video_pref and audio_pref: final_quality_format = f"{video_pref}+{audio_pref}/{video_pref}/{audio_pref}/{DEFAULT_COMBINED_FALLBACK_FORMAT}"
        elif video_pref: final_quality_format = f"{video_pref}/{DEFAULT_COMBINED_FALLBACK_FORMAT}"
        elif audio_pref: final_quality_format = f"{DEFAULT_VIDEO_QUALITY_FORMAT}+{audio_pref}/{audio_pref}/{DEFAULT_COMBINED_FALLBACK_FORMAT}"
        else: logger.warning("No format specified, using default."); final_quality_format = DEFAULT_COMBINED_FALLBACK_FORMAT
        logger.info(f"Using combined yt-dlp format: {final_quality_format}")

        self.stop_event.clear()
        self.review_list.clear()
        self.is_reviewing = False # Ensure review flag is reset
        while not self.gui_queue.empty(): self.gui_queue.get_nowait()
        while not self.manual_select_queue.empty(): self.manual_select_queue.get_nowait() # Clear manual queue too

        self._show_standard_buttons() # Ensure standard buttons shown
        # self._hide_merge_button() # No merge button
        self.start_button.config(state=tk.DISABLED)
        self.review_button.config(text="Review Pending (0)", state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        options = {
            'final_quality_format': final_quality_format,
            'search_results_count': self.search_results_count.get(),
            'download_delay': self.download_delay.get(),
            'override_existing': self.override_existing.get(), # <-- Pass override flag
            'no_trust_mode': self.no_trust_mode.get() # <-- Pass no trust flag
        }
        is_interactive = self.interactive_mode.get() # Get mode state

        self.processing_thread = threading.Thread(
            target=worker_thread_main,
            args=(
                music_dir, output_dir, options, list(self.file_list_data.keys()),
                self.gui_queue,
                self.manual_select_queue, # Pass manual queue for interactive mode
                self.stop_event,
                is_interactive # Pass mode flag
            ),
            daemon=True
        )
        self.processing_thread.start(); logger.info(f"Processing thread started (Interactive: {is_interactive}, Override: {options['override_existing']}, NoTrust: {options['no_trust_mode']})")

    def stop_processing(self):
        if self.processing_thread and self.processing_thread.is_alive():
            logger.info("Stop requested by user."); self.stop_event.set()
            try: self.manual_select_queue.put_nowait("stop_signal") # Unblock worker if waiting
            except queue.Full: logger.warning("Manual select queue full during stop.")
            except Exception as e: logger.error(f"Error putting stop signal in queue: {e}")
            self.stop_button.config(state=tk.DISABLED, text="Stopping...")
        else:
             # Also handle stopping during review phase
             if self.is_reviewing:
                 self.is_reviewing = False # Stop the review loop
                 self.review_list.clear() # Clear pending items
                 logger.info("Review phase stopped by user.")
                 # Update status of the item currently being reviewed, if any
                 if self.current_review_item and self.current_review_item.get('filepath'):
                     self.update_file_status(self.current_review_item['filepath'], STATUS_SKIPPED_MANUAL, "Review Stopped")
                     self.current_review_item = None

             # Reset buttons
             self._update_button_states_after_processing() # Use helper to set correct states
             if hasattr(self, 'stop_button') and self.stop_button.winfo_exists():
                 self.stop_button.config(state=tk.DISABLED, text="Stop")


    def on_closing(self):
        # (Closing logic remains the same)
        if self.processing_thread and self.processing_thread.is_alive():
            if self.winfo_exists():
                if messagebox.askyesno("Quit?", "Processing is ongoing. Stop and quit?", parent=self):
                    self.stop_processing(); self.after(500, self.destroy)
                else: return
            else: self.stop_processing(); self.after(500, self.destroy)
        else:
             self.is_reviewing = False # Ensure review loop stops if closing during review
             self.destroy()

    # --- REMOVED: Merge Function ---
    # def start_merge(self): ...


# --- Main Execution ---
# (Main execution remains the same)
if __name__ == "__main__":
    log_handler_console = logging.StreamHandler(sys.stderr)
    log_handler_console.setFormatter(log_formatter)
    logger.addHandler(log_handler_console)
    app = None
    try:
        app = App()
        if app and app.winfo_exists() and hasattr(app, 'log_text'):
             logger.removeHandler(log_handler_console)
             app.mainloop()
        elif app and not app.winfo_exists(): logger.info("App init failed or window closed early.")
        else: logger.critical("App object creation failed.")
    except tk.TclError as e:
         logger.critical(f"Tkinter GUI Error: {e}", exc_info=True); print(f"FATAL ERROR: GUI Error.\n{e}\nCheck {LOG_FILE}.", file=sys.stderr); sys.exit(1)
    except Exception as e:
        logger.critical(f"GUI Init Error: {e}", exc_info=True); print(f"FATAL ERROR: GUI Error.\n{e}\nCheck {LOG_FILE}.", file=sys.stderr); sys.exit(1)
