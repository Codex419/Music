import os
import logging
import re
import json
import time
import requests
import subprocess
from pathlib import Path

# Try importing dependencies
try:
    import tidalapi
    TIDAL_AVAILABLE = True
except ImportError:
    TIDAL_AVAILABLE = False

try:
    import deezer
    DEEZER_AVAILABLE = True
except ImportError:
    DEEZER_AVAILABLE = False

try:
    import yt_dlp
    YT_DLP_AVAILABLE = True
except ImportError:
    YT_DLP_AVAILABLE = False

try:
    import musicbrainzngs
    MUSICBRAINZ_AVAILABLE = True
except ImportError:
    MUSICBRAINZ_AVAILABLE = False

logger = logging.getLogger(__name__)

class Ingest:
    def __init__(self, config):
        self.config = config
        self.tidal_session = None
        self.deezer_client = None

        if MUSICBRAINZ_AVAILABLE:
            musicbrainzngs.set_useragent("MusicDownloader", "1.0", "contact@example.com")

    # --- Authentication & Init ---
    def _init_tidal(self):
        if not TIDAL_AVAILABLE: return False
        if self.tidal_session and self.tidal_session.check_login(): return True

        try:
            config = tidalapi.Config()
            self.tidal_session = tidalapi.Session(config=config)

            # OAuth 2.0
            token_type = self.config['tidal'].get('token_type', 'Bearer')
            access_token = self.config['tidal'].get('access_token')
            refresh_token = self.config['tidal'].get('refresh_token')
            expiry_time = self.config['tidal'].get('expiry_time')

            if access_token and refresh_token:
                self.tidal_session.load_oauth_session(token_type, access_token, refresh_token, expiry_time)
                if self.tidal_session.check_login():
                    logger.info("Tidal session loaded.")
                    return True
            return False
        except Exception as e:
            logger.error(f"Tidal init failed: {e}")
            return False

    def _init_deezer(self):
        if not DEEZER_AVAILABLE: return False
        if self.deezer_client: return True
        try:
            arl = self.config['deezer'].get('arl')
            headers = {'Cookie': f'arl={arl}'} if arl else {}
            self.deezer_client = deezer.Client(headers=headers)
            return True
        except Exception as e:
            logger.error(f"Deezer init failed: {e}")
            return False

    # --- Search Logic ---
    def search_tidal(self, query, limit=5):
        if not self._init_tidal(): return []
        candidates = []
        try:
            results = self.tidal_session.search(query, models=[tidalapi.Track], limit=limit)
            for track in results['tracks'][:limit]:
                cover_url = None
                try:
                    if hasattr(track.album, 'image'): cover_url = track.album.image(320)
                except: pass

                candidates.append({
                    'source': 'Tidal',
                    'title': track.name,
                    'artist': track.artist.name if track.artist else "Unknown",
                    'album': track.album.name if track.album else "Unknown",
                    'duration': track.duration,
                    'cover_url': cover_url,
                    'obj': track
                })
        except Exception as e:
            logger.error(f"Tidal search error: {e}")
        return candidates

    def search_deezer(self, query, limit=5):
        if not self._init_deezer(): return []
        candidates = []
        try:
            results = self.deezer_client.search(query, limit=limit)
            for track in results[:limit]:
                candidates.append({
                    'source': 'Deezer',
                    'title': track.title,
                    'artist': track.artist.name,
                    'album': track.album.title,
                    'duration': track.duration,
                    'cover_url': track.album.cover_medium,
                    'obj': track
                })
        except Exception as e:
            logger.error(f"Deezer search error: {e}")
        return candidates

    # --- Robust YouTube Video Selection (Legacy Port) ---
    def search_and_select_best_video(self, artist, title, limit=10):
        """
        Robust search for the best official music video using legacy scoring logic.
        Returns the best candidate dict or None.
        """
        if not YT_DLP_AVAILABLE: return None

        # 1. Official Search
        query = f"{artist} - {title} official music video"
        logger.info(f"Searching YouTube for: {query}")
        raw_results = self._yt_search_raw(query, limit)

        # 2. Filter & Score
        selected = self._filter_and_select(raw_results, artist, title)

        # 3. Fallback Search if needed
        if not selected:
            query_simple = f"{artist} - {title}"
            logger.info(f"Fallback search: {query_simple}")
            raw_results_simple = self._yt_search_raw(query_simple, limit)
            selected = self._filter_and_select(raw_results_simple, artist, title)

        return selected

    def _yt_search_raw(self, query, limit):
        """Perform raw search using yt-dlp library."""
        opts = {
            'quiet': True,
            'default_search': f'ytsearch{limit}',
            'noplaylist': True,
            'extract_flat': 'in_playlist', # Get metadata without downloading
            'skip_download': True,
            'ignoreerrors': True,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            try:
                info = ydl.extract_info(query, download=False)
                return info.get('entries', [])
            except Exception as e:
                logger.error(f"yt-dlp search error: {e}")
                return []

    def _filter_and_select(self, videos, artist, title):
        """
        Applies robust scoring logic to select the best video.
        Ported from legacy/main_processor.py.
        """
        if not videos: return None

        candidates = []
        artist_lower = artist.lower()
        title_lower = title.lower()

        negative_keywords = ['lyric', 'cover', 'remix', 'live', 'reaction', 'instrumental',
                             'karaoke', 'parody', 'chipmunk', 'slowed', 'reverb', 'bass boosted',
                             'tutorial', 'lesson', 'interview', 'teaser', 'trailer', 'fan cam',
                             'album version', 'full album', 'topic', 'provided to youtube by']
        positive_keywords = ['official music video', 'official video', 'official audio']

        for vid in videos:
            vid_title = vid.get('title', '')
            vid_title_lower = vid_title.lower()
            channel = vid.get('uploader', '') or vid.get('channel', '')
            channel_lower = channel.lower()

            score = 0
            is_negative = any(nk in vid_title_lower for nk in negative_keywords if nk not in ['official audio', 'topic'])

            # Scoring
            if is_negative:
                score -= 20

            if any(pk in vid_title_lower for pk in positive_keywords):
                score += 10

            # Channel Match
            if artist_lower == channel_lower or f"{artist_lower} official" in channel_lower or "vevo" in channel_lower:
                score += 8
            elif artist_lower in channel_lower:
                score += 5

            # Title Match
            if title_lower in vid_title_lower:
                score += 5

            # Strict Official Check (Priority Return)
            is_official_title = any(pk in vid_title_lower for pk in positive_keywords)
            is_official_channel = (artist_lower in channel_lower or "vevo" in channel_lower)
            if is_official_title and is_official_channel and not is_negative:
                logger.info(f"Prioritized official video: {vid_title}")
                return {
                    'source': 'YouTube',
                    'title': vid_title,
                    'artist': channel,
                    'url': vid.get('url') or vid.get('webpage_url'),
                    'duration': vid.get('duration'),
                    'obj': vid
                }

            if not is_negative and (title_lower in vid_title_lower or score > 0):
                candidates.append({'video': vid, 'score': score})

        # Sort by score
        candidates.sort(key=lambda x: x['score'], reverse=True)

        if candidates:
            best = candidates[0]
            # Threshold check
            if best['score'] >= 5:
                vid = best['video']
                logger.info(f"Selected video by score ({best['score']}): {vid.get('title')}")
                return {
                    'source': 'YouTube',
                    'title': vid.get('title'),
                    'artist': vid.get('uploader'),
                    'url': vid.get('url') or vid.get('webpage_url'),
                    'duration': vid.get('duration'),
                    'obj': vid
                }

        return None

    # --- Download Logic ---
    def download_tidal(self, track_obj, output_path):
        # ... (Existing Tidal Download logic) ...
        try:
            if hasattr(self.tidal_session.track, 'get_url'):
                url = self.tidal_session.track.get_url(track_obj.id)
            else:
                url = track_obj.get_url()

            if url:
                r = requests.get(url, stream=True)
                with open(output_path, 'wb') as f:
                    for chunk in r.iter_content(1024): f.write(chunk)
                return output_path
        except Exception as e:
            logger.error(f"Tidal DL error: {e}")
        return None

    def download_deezer(self, track_obj, output_path):
        # Placeholder - Real implementation requires encryption handling
        return None

    def download_youtube_video(self, video_obj, output_path):
        """Download video using yt-dlp."""
        url = video_obj.get('webpage_url') or video_obj.get('url')
        if not url: return None

        opts = {
            'quiet': True,
            'outtmpl': output_path,
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'noplaylist': True,
            'overwrites': True
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
            if os.path.exists(output_path): return output_path
        except Exception as e:
            logger.error(f"YouTube DL error: {e}")
        return None

    # --- Expansion & Helpers ---
    def expand_artist(self, artist_name):
        tracks = []
        if self._init_tidal():
            try:
                res = self.tidal_session.search(artist_name, models=[tidalapi.Artist])
                if res['artists']:
                    top = res['artists'][0].get_top_tracks()
                    tracks = [f"{t.artist.name} - {t.name}" for t in top]
            except: pass
        return tracks

    def expand_album(self, album_name):
        tracks = []
        if self._init_tidal():
            try:
                res = self.tidal_session.search(album_name, models=[tidalapi.Album])
                if res['albums']:
                    t = res['albums'][0].tracks()
                    tracks = [f"{tr.artist.name} - {tr.name}" for tr in t]
            except: pass
        return tracks

    def parse_playlist(self, url):
        """
        Parses various playlist URLs (Spotify, Tidal, YouTube).
        Returns list of "Artist - Title" strings.
        """
        tracks = []

        # Spotify
        if "spotify.com" in url:
            # Basic HTML parsing (fallback) or API
            try:
                r = requests.get(url)
                matches = re.findall(r'"name":"(.*?)","artists":\[{"name":"(.*?)"', r.text)
                tracks = [f"{a} - {s}" for s, a in matches]
            except: pass

        # Tidal
        elif "tidal.com" in url:
            # Need tidal session
            pass

        # YouTube Playlist (Reverse Logic Preparation)
        elif "youtube.com" in url and "list=" in url:
            # Use yt-dlp to get titles
            opts = {'extract_flat': True, 'quiet': True}
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if 'entries' in info:
                    for entry in info['entries']:
                        # We hope the title is "Artist - Title"
                        tracks.append(entry['title'])

        return list(set(tracks))

    def reverse_search_audio(self, video_title):
        """
        Given a video title (e.g. from a YouTube playlist), find the best audio candidate.
        Reverse Logic: Video Title -> Audio Track
        """
        # Heuristic cleaning
        clean_title = re.sub(r'\(.*?\)|\[.*?\]', '', video_title).strip() # Remove brackets
        clean_title = clean_title.replace("Official Video", "").replace("Official Audio", "").strip()

        return self.search_tidal(clean_title, limit=1)

if __name__ == "__main__":
    import argparse
    import yaml

    # Load config
    try:
        with open("config.yaml", "r") as f:
            config = yaml.safe_load(f)
    except FileNotFoundError:
        config = {'tidal': {}, 'deezer': {}}
        print("Warning: config.yaml not found, using empty config.")

    parser = argparse.ArgumentParser(description="Ingest Module CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Search Tidal
    p_tidal = subparsers.add_parser("search_tidal")
    p_tidal.add_argument("query", help="Search query")

    # Search Deezer
    p_deezer = subparsers.add_parser("search_deezer")
    p_deezer.add_argument("query", help="Search query")

    # Search YouTube
    p_yt = subparsers.add_parser("search_youtube")
    p_yt.add_argument("query", help="Search query (Artist - Title)")

    # Download YouTube
    p_dl_yt = subparsers.add_parser("download_youtube")
    p_dl_yt.add_argument("url", help="YouTube URL")
    p_dl_yt.add_argument("output", help="Output filename")

    args = parser.parse_args()
    ingest = Ingest(config)

    if args.command == "search_tidal":
        results = ingest.search_tidal(args.query)
        print(json.dumps([{'title': r['title'], 'artist': r['artist']} for r in results], indent=2))

    elif args.command == "search_deezer":
        results = ingest.search_deezer(args.query)
        print(json.dumps([{'title': r['title'], 'artist': r['artist']} for r in results], indent=2))

    elif args.command == "search_youtube":
        # Split query if possible
        parts = args.query.split(" - ")
        artist = parts[0]
        title = parts[1] if len(parts) > 1 else args.query
        result = ingest.search_and_select_best_video(artist, title)
        if result:
            print(json.dumps({'title': result['title'], 'url': result['url']}, indent=2))
        else:
            print("No suitable video found.")

    elif args.command == "download_youtube":
        # Mock obj structure
        obj = {'webpage_url': args.url}
        res = ingest.download_youtube_video(obj, args.output)
        print(f"Download result: {res}")
