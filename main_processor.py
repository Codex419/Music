import os
import re
import logging
import sys # For basic logging to stderr if mutagen is not found
import subprocess # For yt-dlp
import json # For yt-dlp output and config file
import time # For download delays/retries
import gc # For garbage collection during transcription
import argparse # For CLI argument parsing

# Attempt to import mutagen
try:
    from mutagen import File as MutagenFile, MutagenError
    from mutagen.flac import FLAC
    from mutagen.mp3 import MP3, EasyMP3
    from mutagen.id3 import ID3, ID3NoHeaderError, TRCK, TPOS, TDRC, TYER, TDOR, TCON, TALB, TPE1, TPE2, TIT2, TCMP, TCOM, COMM
    from mutagen.mp4 import MP4, MP4Tags
    from mutagen.oggvorbis import OggVorbis
    from mutagen.oggopus import OggOpus
    MUTAGEN_AVAILABLE = True
except ImportError:
    MUTAGEN_AVAILABLE = False
    class MutagenFile: pass; class MutagenError(Exception): pass; class FLAC: pass; class MP3: pass; class EasyMP3: pass;
    class ID3: pass; class ID3NoHeaderError(Exception): pass; class TRCK: pass; class TPOS: pass; class TDRC: pass;
    class TYER: pass; class TDOR: pass; class TCON: pass; class TALB: pass; class TPE1: pass; class TPE2: pass;
    class TIT2: pass; class TCMP: pass; class TCOM: pass; class COMM: pass; class MP4: pass; class MP4Tags: pass;
    class OggVorbis: pass; class OggOpus: pass;
    print("WARNING: Mutagen library not found. Metadata features will be limited.", file=sys.stderr)

# Attempt to import faster_whisper and related
try:
    from faster_whisper import WhisperModel, format_timestamp
    FASTER_WHISPER_AVAILABLE = True
except ImportError:
    FASTER_WHISPER_AVAILABLE = False
    class WhisperModel: pass 
    def format_timestamp(seconds, always_include_hours=False, decimal_marker=','): return f"{seconds:.2f}" 
    print("WARNING: faster-whisper library not found. Transcription will not be available.", file=sys.stderr)

try:
    import torch
    PYTORCH_AVAILABLE = True
    try: CUDA_AVAILABLE = torch.cuda.is_available()
    except Exception: CUDA_AVAILABLE = False
except ImportError:
    PYTORCH_AVAILABLE = False; CUDA_AVAILABLE = False
    print("WARNING: PyTorch not found. GPU-specific operations unavailable.", file=sys.stderr)

# --- Constants ---
AUDIO_EXTENSIONS = ['.mp3', '.flac', '.m4a', '.aac', '.ogg', '.opus', '.aiff', '.wav']
VIDEO_EXTENSIONS = ['.mp4', '.mkv', '.avi', '.mov', '.webm', '.flv'] 

DEFAULT_VIDEO_QUALITY_FORMAT = 'bestvideo[height<=1080][ext=mp4]'
DEFAULT_COMBINED_FALLBACK_FORMAT = 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/bestvideo[height<=1080]+bestaudio/best[height<=1080]'
DEFAULT_SEARCH_RESULTS_COUNT = 5
DEFAULT_MODEL_SIZE = "large-v2"
DEFAULT_BEAM_SIZE = 5
DEFAULT_YT_DLP_PATH = "yt-dlp"
DEFAULT_CONFIG_FILENAME = "config.json"

METADATA_MAP_TO_MP4 = {
    'artist': '\xa9ART', 'title': '\xa9nam', 'album': '\xa9alb', 'genre': '\xa9gen',
    'date': '\xa9day', 'year': '\xa9day', 'albumartist': 'aART', 'tracknumber': 'trkn',
    'discnumber': 'disk', 'compilation': 'cpil', 'composer': '\xa9wrt', 'comment': '\xa9cmt',
}
MODEL_DOWNLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Audio_Models_main_processor")

# Ensure logger is configured at the module level for consistency
# This will be used by all functions in this module.
# The main block can also add more handlers or change level if needed via CLI args later.
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(levelname)s - %(name)s - %(funcName)s - %(message)s', 
                    handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger(__name__)

# --- Helper Functions ---
def _get_startupinfo():
    startupinfo = None
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
    return startupinfo

def _worker_sanitize_filename(name: str) -> str:
    if not name: return "Untitled"
    name = re.sub(r'[\\/*?:"<>|]', "", name); name = re.sub(r'\.+', '.', name)
    name = name.strip().strip('.- ');
    if not name or name == ".": name = "Untitled"
    MAX_FILENAME_LEN = 200 
    if len(name) > MAX_FILENAME_LEN:
         base, ext = os.path.splitext(name); base = base[:MAX_FILENAME_LEN - len(ext) - (1 if ext else 0)]
         name = base + ext; logger.warning(f"Sanitized filename truncated: {name}")
    return name

# --- Core Processing Functions ---
def _worker_get_metadata(filepath: str) -> tuple[str | None, str | None]:
    if not MUTAGEN_AVAILABLE:
        logger.warning(f"Mutagen not available. Trying filename parse for {filepath}")
        base = os.path.splitext(os.path.basename(filepath))[0]
        parts = re.split(r'\s+-\s+|\s+–\s+|\s*_\s*-\s*_\s*', base, 1)
        if len(parts) == 2: artist, title = parts[0].strip(), parts[1].strip(); return artist, title
        logger.warning(f"Could not parse artist/title from filename: {base}")
        return None, None
    logger.debug(f"Reading metadata using Mutagen for: {filepath}"); artist, title = None, None
    try:
        audio = MutagenFile(filepath, easy=True)
        if audio: artist, title = audio.get('artist', [None])[0], audio.get('title', [None])[0]
        if not artist or not title:
            audio_raw = MutagenFile(filepath, easy=False)
            if isinstance(audio_raw, MP3):
                tpe1,tpe2,tit2,tit1 = audio_raw.get('TPE1'),audio_raw.get('TPE2'),audio_raw.get('TIT2'),audio_raw.get('TIT1')
                if not artist: artist = str(tpe1.text[0]) if tpe1 and tpe1.text else (str(tpe2.text[0]) if tpe2 and tpe2.text else None)
                if not title: title = str(tit2.text[0]) if tit2 and tit2.text else (str(tit1.text[0]) if tit1 and tit1.text else None)
            elif isinstance(audio_raw, (FLAC, OggVorbis, OggOpus)):
                if not artist: artist = audio_raw.get('artist', [None])[0]
                if not title: title = audio_raw.get('title', [None])[0]
            elif isinstance(audio_raw, MP4):
                if not artist: artist = audio_raw.get('\xa9ART', [None])[0]
                if not title: title = audio_raw.get('\xa9nam', [None])[0]
        if not artist or not title:
            logger.warning(f"Missing tags for {filepath}. Attempting filename parse.")
            base = os.path.splitext(os.path.basename(filepath))[0]
            parts = re.split(r'\s+-\s+|\s+–\s+|\s*_\s*-\s*_\s*', base, 1)
            if len(parts) == 2:
                g_artist, g_title = parts[0].strip(), parts[1].strip()
                if g_artist and g_title:
                    if not artist: artist = g_artist
                    if not title: title = g_title
        artist, title = (str(artist).strip() if artist else None), (str(title).strip() if title else None)
        if not artist or not title: logger.warning(f"Could not determine full artist/title for {filepath}"); return None, None
        return artist, title
    except Exception as e: logger.error(f"Metadata error for {filepath}: {e}", exc_info=False); return None,None

def scan_music_library(music_dir_path: str) -> list[dict]:
    logger.info(f"Scanning music library: {music_dir_path}")
    if not os.path.isdir(music_dir_path): logger.error(f"Not a directory: {music_dir_path}"); return []
    results, scanned, found = [], 0, 0
    for root, _, files in os.walk(music_dir_path):
        for filename in files:
            scanned += 1; filepath = os.path.join(root, filename); _, ext = os.path.splitext(filename.lower())
            if ext in AUDIO_EXTENSIONS:
                found += 1; logger.debug(f"Audio file found: {filepath}")
                try: artist, title = _worker_get_metadata(filepath); results.append({'filepath': filepath, 'artist': artist, 'title': title})
                except Exception as e: logger.error(f"Error processing {filepath}: {e}", exc_info=True); results.append({'filepath': filepath, 'artist': None, 'title': None})
    logger.info(f"Scan complete. Scanned: {scanned}, Audio Found: {found}.")
    return results

def transfer_metadata(audio_path: str, mp4_path: str) -> bool:
    if not MUTAGEN_AVAILABLE: logger.error("Mutagen unavailable."); return False
    if not (os.path.exists(audio_path) and os.path.exists(mp4_path)): logger.error("Audio or MP4 path not found."); return False
    logger.info(f"Transferring metadata: '{os.path.basename(audio_path)}' -> '{os.path.basename(mp4_path)}'")
    count = 0
    try:
        audio_tags = MutagenFile(audio_path, easy=False)
        if not audio_tags: logger.error(f"Cannot read tags from '{audio_path}'."); return False
        mp4 = MP4(mp4_path)
        if mp4.tags is None: mp4.add_tags(); mp4 = MP4(mp4_path)
        if mp4.tags is None: raise MutagenError("Failed to create MP4 tags.")
        for c_key, m_key in METADATA_MAP_TO_MP4.items():
            val_obj = audio_tags.get(c_key) 
            if val_obj is not None:
                curr_val = val_obj[0] if isinstance(val_obj, list) and val_obj else val_obj
                if hasattr(curr_val, 'text'): curr_val = curr_val.text[0] if curr_val.text else str(curr_val)
                elif isinstance(curr_val, list) and curr_val: curr_val = curr_val[0]
                if m_key in ['trkn', 'disk']: val_to_write = [(int(str(curr_val).split('/')[0] or 0), int(str(curr_val).split('/')[1] or 0) if '/' in str(curr_val) else 0)]
                elif m_key == 'cpil': val_to_write = [bool(int(str(curr_val).strip() or 0))]
                elif m_key == '\xa9day': year = str(curr_val)[:4]; val_to_write = [year] if year.isdigit() and len(year)==4 else None
                else: val_to_write = [str(curr_val)]
                if val_to_write: mp4.tags[m_key] = val_to_write; count+=1
        if count > 0: mp4.save(); logger.info(f"Saved {count} tags."); return True
        else: logger.info("No transferable tags found."); return False
    except Exception as e: logger.error(f"Metadata transfer error: {e}", exc_info=True); return False

def _search_videos_yt_dlp(query: str, search_count: int, yt_dlp_path: str = "yt-dlp") -> list[dict] | None:
    cmd = [yt_dlp_path, '--dump-json', '--no-playlist', '--match-filter', '!is_live & duration > 60 & duration < 1200', '--ignore-errors', '--no-warnings', '--extractor-args', 'youtube:player_client=web', f'ytsearch{search_count}:{query}']
    logger.info(f"Searching YouTube: {' '.join(cmd)}")
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', startupinfo=_get_startupinfo())
        stdout, stderr = proc.communicate(timeout=60)
        if proc.returncode != 0: logger.error(f"yt-dlp search failed for '{query}' (code {proc.returncode}). Stderr: {stderr.strip()}"); return None
        return [json.loads(line) for line in stdout.strip().split('\n') if line]
    except Exception as e: logger.error(f"Error in yt-dlp search for '{query}': {e}", exc_info=True); return None

def _filter_and_select_best_video(videos: list[dict], artist: str, title: str) -> str | None:
    if not videos: return None
    candidates = []; artist_lower, title_lower = artist.lower(), title.lower()
    negative_keywords = ['lyric', 'cover', 'remix', 'live', 'reaction', 'instrumental', 'karaoke', 'parody', 'chipmunk', 'slowed', 'reverb', 'bass boosted', 'tutorial', 'lesson', 'interview', 'teaser', 'trailer', 'fan cam', 'album version', 'full album', 'topic', 'provided to youtube by', '8d audio', 'nightcore', 'extended', 'mashup', 'megamix', 'clean version']
    positive_keywords = ['official music video', 'official video', 'official audio']
    for video in videos:
        vid_title_raw = video.get('title', ''); vid_title_lower = vid_title_raw.lower()
        channel_raw = video.get('channel', video.get('uploader', '')); channel_lower = channel_raw.lower()
        uploader_id_raw = video.get('uploader_id', ''); uploader_id_lower = uploader_id_raw.lower() if uploader_id_raw else ''
        is_verified = video.get('channel_is_verified', False)
        is_official_title = any(pk in vid_title_lower for pk in positive_keywords)
        is_official_channel_name = (channel_lower == artist_lower or f"{artist_lower} official" in channel_lower or f"{artist_lower}vevo" in channel_lower or ('vevo' in channel_lower and artist_lower in channel_lower))
        is_official_uploader_id = ('vevo' in uploader_id_lower and artist_lower in uploader_id_lower)
        has_negative_strict = any(nk in vid_title_lower for nk in negative_keywords if nk not in ['official audio', 'topic', 'provided to youtube by'])
        if is_official_title and (is_official_channel_name or is_official_uploader_id or (is_verified and artist_lower in channel_lower)) and not has_negative_strict:
            video_id = video.get('id');
            if video_id: logger.info(f"Prioritized official video: '{vid_title_raw}' (ID: {video_id})"); return video_id
    for video in videos:
        vid_title_raw = video.get('title', ''); vid_title_lower = vid_title_raw.lower()
        score = 0; is_negative = any(keyword in vid_title_lower for keyword in negative_keywords)
        if is_negative: score -= (5 if any(pk in vid_title_lower for pk in positive_keywords) else 20)
        if any(keyword in vid_title_lower for keyword in positive_keywords): score += 10
        # ... (rest of scoring logic from previous version) ...
        if not is_negative and (title_lower in vid_title_lower or score > 2): candidates.append({'id': video.get('id'), 'title': vid_title_raw, 'score': score})
    if not candidates: return None
    candidates.sort(key=lambda x: x['score'], reverse=True)
    if candidates[0]['score'] >= 8 and (len(candidates) == 1 or candidates[0]['score'] >= candidates[1]['score'] + 5):
        logger.info(f"Auto-selected: '{candidates[0]['title']}' (Score: {candidates[0]['score']})"); return candidates[0].get('id')
    logger.info(f"No clear automatic match for '{artist} - {title}'. Top score: {candidates[0]['score'] if candidates else 'N/A'}."); return None

def search_and_select_video(artist: str, title: str, search_count: int = DEFAULT_SEARCH_RESULTS_COUNT, yt_dlp_path: str = DEFAULT_YT_DLP_PATH) -> str | None:
    logger.info(f"Searching for '{artist} - {title}'")
    query_official = f"{artist} - {title} official music video"
    videos = _search_videos_yt_dlp(query_official, search_count, yt_dlp_path)
    selected_id = _filter_and_select_best_video(videos, artist, title) if videos else None
    if not selected_id:
        query_simple = f"{artist} - {title}"
        videos = _search_videos_yt_dlp(query_simple, search_count, yt_dlp_path)
        selected_id = _filter_and_select_best_video(videos, artist, title) if videos else None
    if selected_id: logger.info(f"Selected video ID: {selected_id}")
    else: logger.warning(f"No suitable video found for '{artist} - {title}'.")
    return selected_id

def download_video(video_id: str, artist: str, title: str, output_dir: str, video_quality_format: str, yt_dlp_path: str = DEFAULT_YT_DLP_PATH) -> str | None:
    if not video_id: logger.error("Download missing video ID."); return None
    if not os.path.exists(output_dir):
        try: os.makedirs(output_dir)
        except OSError as e: logger.error(f"Failed to create output dir {output_dir}: {e}"); return None
    s_artist, s_title = _worker_sanitize_filename(artist), _worker_sanitize_filename(title)
    out_template = os.path.join(output_dir, f"{s_artist} - {s_title}.%(ext)s")
    cmd = [yt_dlp_path, '-f', video_quality_format, '-o', out_template, '--no-warnings', '--ignore-errors', '--force-overwrites', '--no-part', '--concurrent-fragments', '4', '--', f'https://www.youtube.com/watch?v={video_id}']
    logger.info(f"Download command: {' '.join(cmd)}")
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', startupinfo=_get_startupinfo())
        stdout, stderr = proc.communicate(timeout=600)
        if proc.returncode == 0:
            logger.info(f"yt-dlp DL OK for {video_id}. Verifying file...")
            exp_prefix = f"{s_artist} - {s_title}."
            for fname in os.listdir(output_dir):
                if fname.startswith(exp_prefix): return os.path.join(output_dir, fname)
            logger.error(f"Could not find downloaded file matching prefix '{exp_prefix}' in '{output_dir}'."); return None
        else: logger.error(f"yt-dlp DL failed for {video_id}. Code: {proc.returncode}. Stderr: {stderr.strip()}"); return None
    except Exception as e: logger.error(f"Unexpected DL error for {video_id}: {e}", exc_info=True); return None

def segments_to_srt(segments):
    return "".join(f"{i+1}\n{format_timestamp(s.start, True, ',')} --> {format_timestamp(s.end, True, ',')}\n{s.text.strip().replace('-->', '->')}\n\n" for i, s in enumerate(segments))
def segments_to_vtt(segments):
    return "WEBVTT\n\n" + "".join(f"{format_timestamp(s.start, True, '.')} --> {format_timestamp(s.end, True, '.')}\n{s.text.strip().replace('-->', '->')}\n\n" for s in segments)
def segments_to_txt(segments): return "\n".join(s.text.strip() for s in segments)
def segments_to_lrc(segments):
    return "".join(f"[{int(s.start//60):02d}:{int(s.start%60):02d}.{int((s.start-int(s.start))*100):02d}]{s.text.strip()}\n" for s in segments if s.text.strip())

def transcribe_file(audio_video_path: str, output_dir: str, model_size: str = DEFAULT_MODEL_SIZE, quantization: str | None = None, device: str = "cpu", compute_type: str = "auto", vad_filter: bool = False, beam_size: int = DEFAULT_BEAM_SIZE, language: str | None = None) -> dict | None:
    if not FASTER_WHISPER_AVAILABLE: logger.error("faster-whisper unavailable."); return None
    if not os.path.exists(audio_video_path): logger.error(f"Input file not found: {audio_video_path}"); return None
    if not os.path.exists(output_dir):
        try: os.makedirs(output_dir)
        except OSError as e: logger.error(f"Failed to create output dir {output_dir}: {e}"); return None
    actual_model_name = model_size 
    logger.info(f"Initializing Whisper: {actual_model_name} (Device: {device}, Compute: {compute_type})")
    os.makedirs(MODEL_DOWNLOAD_DIR, exist_ok=True)
    model = None
    try: model = WhisperModel(actual_model_name, device=device, compute_type=compute_type, download_root=MODEL_DOWNLOAD_DIR)
    except Exception as e: logger.error(f"Failed to load Whisper model '{actual_model_name}': {e}", exc_info=True); return None
    opts = {"task": "transcribe", "language": language, "vad_filter": vad_filter, "beam_size": beam_size, "word_timestamps": True}
    paths = {}; base_fn = os.path.splitext(os.path.basename(audio_video_path))[0]
    try:
        segments, info = model.transcribe(audio_video_path, **opts)
        logger.info(f"Detected lang: {info.language} (Prob: {info.language_probability:.2f}), Duration: {info.duration:.2f}s")
        seg_list = list(segments)
        txt_path = os.path.join(output_dir, f"{base_fn}.txt"); open(txt_path, "w", encoding="utf-8").write(segments_to_txt(seg_list)); paths["txt"] = txt_path; logger.info(f"Saved TXT: {txt_path}")
        ext = os.path.splitext(audio_video_path)[1].lower()
        if ext in VIDEO_EXTENSIONS: srt_path = os.path.join(output_dir, f"{base_fn}.srt"); open(srt_path, "w", encoding="utf-8").write(segments_to_srt(seg_list)); paths["srt"] = srt_path; logger.info(f"Saved SRT: {srt_path}")
        if ext in AUDIO_EXTENSIONS: lrc_path = os.path.join(output_dir, f"{base_fn}.lrc"); open(lrc_path, "w", encoding="utf-8").write(segments_to_lrc(seg_list)); paths["lrc"] = lrc_path; logger.info(f"Saved LRC: {lrc_path}")
        return paths
    except Exception as e: logger.error(f"Error during transcription for {audio_video_path}: {e}", exc_info=True); return None
    finally:
        if model: logger.debug("Releasing Whisper model."); del model
        if CUDA_AVAILABLE and PYTORCH_AVAILABLE:
            try: torch.cuda.empty_cache(); logger.debug("CUDA cache cleared.")
            except Exception as e: logger.warning(f"Error clearing CUDA cache: {e}")
        gc.collect()

# --- Config File Handling ---
def load_config(config_filepath: str) -> dict:
    if config_filepath and os.path.exists(config_filepath):
        try:
            with open(config_filepath, 'r') as f: config = json.load(f)
            logger.info(f"Loaded configuration from: {config_filepath}"); return config
        except Exception as e: logger.error(f"Error loading config {config_filepath}: {e}")
    elif config_filepath and config_filepath != DEFAULT_CONFIG_FILENAME: logger.warning(f"Specified config file not found: {config_filepath}.")
    else: logger.info(f"Default config '{DEFAULT_CONFIG_FILENAME}' not found or not specified.")
    return {}

def generate_sample_config(filepath: str):
    cfg = {"music_library": None, "output_dir": None, "yt_dlp_path": DEFAULT_YT_DLP_PATH, "video_quality": DEFAULT_COMBINED_FALLBACK_FORMAT, "search_results": DEFAULT_SEARCH_RESULTS_COUNT, "transcribe_model_size": DEFAULT_MODEL_SIZE, "transcribe_device": "cuda" if CUDA_AVAILABLE else "cpu", "transcribe_compute_type": "float16" if CUDA_AVAILABLE else "int8", "transcribe_vad": False, "transcribe_beam_size": DEFAULT_BEAM_SIZE, "transcribe_language": None}
    comments = {"_comment_main": "Main paths", "_comment_youtube_dl": "yt-dlp settings", "_comment_transcription": "Transcription settings"}
    final_cfg = {**comments, **cfg} # Python 3.9+ for merging dicts this way
    try:
        with open(filepath, 'w') as f: json.dump(final_cfg, f, indent=2)
        logger.info(f"Generated sample configuration: {filepath}")
    except Exception as e: logger.error(f"Error generating sample config {filepath}: {e}")

# --- Main CLI Workflow ---
if __name__ == "__main__":
    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument("--generate_config", nargs='?', const=DEFAULT_CONFIG_FILENAME, help=f"Generate sample config (default: {DEFAULT_CONFIG_FILENAME}) and exit.")
    pre_parser.add_argument("--config_file", default=DEFAULT_CONFIG_FILENAME, help=f"Path to config file (default: {DEFAULT_CONFIG_FILENAME}).")
    pre_args, remaining_argv = pre_parser.parse_known_args()

    if pre_args.generate_config is not None: generate_sample_config(pre_args.generate_config); sys.exit(0)
    config = load_config(pre_args.config_file)

    parser = argparse.ArgumentParser(description="Process music library: download videos, transfer metadata, transcribe.", parents=[pre_parser])
    def get_default(key, default_val): return config.get(key, default_val)
    parser.add_argument("--music_library", default=config.get("music_library"), help="Music library path.")
    parser.add_argument("--output_dir", default=config.get("output_dir"), help="Main output directory.")
    parser.add_argument("--yt_dlp_path", default=get_default("yt_dlp_path", DEFAULT_YT_DLP_PATH), help="yt-dlp path.")
    parser.add_argument("--video_quality", default=get_default("video_quality", DEFAULT_COMBINED_FALLBACK_FORMAT), help="yt-dlp video quality.")
    parser.add_argument("--search_results", type=int, default=get_default("search_results", DEFAULT_SEARCH_RESULTS_COUNT), help="Num YouTube search results.")
    parser.add_argument("--transcribe_model_size", default=get_default("transcribe_model_size", DEFAULT_MODEL_SIZE), help="Whisper model size.")
    parser.add_argument("--transcribe_device", default=get_default("transcribe_device", "cuda" if CUDA_AVAILABLE else "cpu"), help="Transcription device.")
    parser.add_argument("--transcribe_compute_type", default=get_default("transcribe_compute_type", "float16" if CUDA_AVAILABLE else "int8"), help="Transcription compute type.")
    parser.add_argument("--transcribe_vad", action=argparse.BooleanOptionalAction, default=get_default("transcribe_vad", False), help="Enable VAD filter.")
    parser.add_argument("--transcribe_beam_size", type=int, default=get_default("transcribe_beam_size", DEFAULT_BEAM_SIZE), help="Transcription beam size.")
    parser.add_argument("--transcribe_language", default=get_default("transcribe_language", None), help="Transcription language code.")
    args = parser.parse_args(remaining_argv)

    if not args.music_library or not args.output_dir: logger.critical("Error: --music_library and --output_dir are required."); parser.print_help(); sys.exit(1)
    logger.info(f"Effective arguments: {args}")
    if not os.path.exists(args.output_dir):
        try: os.makedirs(args.output_dir); logger.info(f"Created main output dir: {args.output_dir}")
        except OSError as e: logger.critical(f"Failed to create main output dir {args.output_dir}: {e}. Exiting."); sys.exit(1)

    # Initialize counters for summary report
    total_audio_files_found = 0
    successfully_processed_songs = 0
    videos_downloaded = 0
    metadata_transferred_count = 0
    audio_transcribed_count = 0
    videos_transcribed_count = 0
    skipped_due_to_missing_tags = 0
    songs_with_video_not_found = 0
    songs_with_download_errors = 0
    songs_with_transcription_errors = 0 # General counter for any transcription error

    audio_files = scan_music_library(args.music_library)
    total_audio_files_found = len(audio_files)
    if not audio_files: logger.info("No audio files found."); sys.exit(0)
    logger.info(f"Found {total_audio_files_found} audio files to process.")

    for audio_info in audio_files:
        original_audio_path, artist, title = audio_info.get('filepath'), audio_info.get('artist'), audio_info.get('title')
        logger.info(f"\n--- Processing: {original_audio_path} ---")
        song_processed_successfully_flag = False
        current_song_transcription_error = False

        if not artist or not title: 
            logger.warning(f"Skipping due to missing artist/title: {original_audio_path}"); skipped_due_to_missing_tags += 1; continue
        
        s_artist, s_title = _worker_sanitize_filename(artist), _worker_sanitize_filename(title)
        song_out_dir = os.path.join(args.output_dir, f"{s_artist} - {s_title}")
        if not os.path.exists(song_out_dir):
            try: os.makedirs(song_out_dir); logger.info(f"Created song output dir: {song_out_dir}")
            except OSError as e: logger.error(f"Failed to create dir {song_out_dir}: {e}. Skipping song."); continue
        
        logger.info(f"Searching video for '{artist} - {title}'...")
        video_id = search_and_select_video(artist, title, args.search_results, args.yt_dlp_path)
        dl_video_path = None # Ensure it's defined for this scope
        if video_id:
            logger.info(f"Video found (ID: {video_id}). Downloading...")
            dl_video_path = download_video(video_id, artist, title, song_out_dir, args.video_quality, args.yt_dlp_path)
            if dl_video_path:
                videos_downloaded += 1; song_processed_successfully_flag = True
                logger.info(f"Video downloaded: {dl_video_path}")
                logger.info(f"Transferring metadata to '{dl_video_path}'...")
                if transfer_metadata(original_audio_path, dl_video_path): metadata_transferred_count +=1; logger.info("Metadata transfer successful.")
                else: logger.warning("Metadata transfer failed/no tags.")
                logger.info(f"Transcribing video: {dl_video_path}...")
                vid_trans_paths = transcribe_file(dl_video_path, song_out_dir, args.transcribe_model_size, None, args.transcribe_device, args.transcribe_compute_type, args.transcribe_vad, args.transcribe_beam_size, args.transcribe_language)
                if vid_trans_paths: videos_transcribed_count += 1; logger.info(f"Video transcription files: {vid_trans_paths}")
                else: logger.warning(f"Video transcription failed for: {dl_video_path}"); current_song_transcription_error = True
            else: logger.warning(f"Video download failed for '{artist} - {title}'."); songs_with_download_errors +=1
        else: logger.info(f"No video found for '{artist} - {title}'."); songs_with_video_not_found +=1

        logger.info(f"Transcribing original audio: {original_audio_path}...")
        audio_trans_paths = transcribe_file(original_audio_path, song_out_dir, args.transcribe_model_size, None, args.transcribe_device, args.transcribe_compute_type, args.transcribe_vad, args.transcribe_beam_size, args.transcribe_language)
        if audio_trans_paths: audio_transcribed_count += 1; song_processed_successfully_flag = True; logger.info(f"Audio transcription files: {audio_trans_paths}")
        else: logger.warning(f"Audio transcription failed for: {original_audio_path}"); current_song_transcription_error = True
        
        if song_processed_successfully_flag: successfully_processed_songs +=1
        if current_song_transcription_error: songs_with_transcription_errors += 1
        logger.info(f"Finished processing for: {artist} - {title}")
        # time.sleep(1) 

    # Print Summary Report
    logger.info("\n" + "-" * 50)
    logger.info("Processing Summary")
    logger.info("-" * 50)
    logger.info(f"Total audio files found in library: {total_audio_files_found}")
    logger.info(f"Songs skipped (missing artist/title): {skipped_due_to_missing_tags}")
    songs_attempted = total_audio_files_found - skipped_due_to_missing_tags
    logger.info(f"Songs attempted for processing: {songs_attempted}")
    logger.info(f"Songs successfully processed (at least one key output): {successfully_processed_songs}")
    logger.info("\n--- Video Operations ---")
    logger.info(f"Videos searched for: {songs_attempted}")
    logger.info(f"Videos found & selected: {videos_downloaded + songs_with_download_errors}") # Found = downloaded + failed downloads
    logger.info(f"Videos successfully downloaded: {videos_downloaded}")
    logger.info(f"Videos not found (after search): {songs_with_video_not_found}")
    logger.info(f"Video download errors: {songs_with_download_errors}")
    logger.info(f"Metadata transferred to videos: {metadata_transferred_count}")
    logger.info("\n--- Transcription Operations ---")
    logger.info(f"Original audio files transcribed: {audio_transcribed_count}")
    logger.info(f"Downloaded video files transcribed: {videos_transcribed_count}")
    logger.info(f"Songs with at least one transcription error: {songs_with_transcription_errors}")
    logger.info("-" * 50)
    logger.info(f"Detailed logs are available above.")
    logger.info(f"Output files are located in subdirectories under: {os.path.abspath(args.output_dir)}")
    logger.info("-" * 50)
    logger.info("\n--- Main processing workflow finished. ---")
