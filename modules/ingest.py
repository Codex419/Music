import os
import logging
import re
import json
import time
from pathlib import Path
import requests

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

try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False

logger = logging.getLogger(__name__)

class Ingest:
    def __init__(self, config):
        self.config = config
        self.tidal_session = None
        self.deezer_client = None

        if MUSICBRAINZ_AVAILABLE:
            musicbrainzngs.set_useragent("MusicDownloader", "1.0", "contact@example.com")

    def _init_tidal(self):
        if not TIDAL_AVAILABLE: return False

        # Check if session is already valid
        if self.tidal_session:
            if self.tidal_session.check_login():
                return True
            else:
                logger.warning("Tidal session expired or invalid. Attempting reload.")

        try:
            # Initialize Session
            config = tidalapi.Config()
            self.tidal_session = tidalapi.Session(config=config)

            # Load tokens from config
            token_type = self.config['tidal'].get('token_type', 'Bearer')
            access_token = self.config['tidal'].get('access_token')
            refresh_token = self.config['tidal'].get('refresh_token')
            expiry_time = self.config['tidal'].get('expiry_time')

            if access_token and refresh_token:
                try:
                    # Convert expiry to datetime if needed or check library expectations
                    # tidalapi expects expiry_time as datetime object usually? Or timestamp?
                    # Using load_oauth_session
                    self.tidal_session.load_oauth_session(
                        token_type,
                        access_token,
                        refresh_token,
                        expiry_time
                    )
                    if self.tidal_session.check_login():
                        logger.info("Tidal session loaded successfully.")
                        return True
                    else:
                        logger.warning("Tidal login check failed after load.")
                except Exception as load_err:
                    logger.error(f"Failed to load saved Tidal session: {load_err}")

            # Fallback to legacy single-token if present (unlikely to work for full access but kept)
            token = self.config['tidal'].get('token')
            if token and not access_token:
                 # Try legacy login? Not supported well in v0.7+
                 pass

            return False
        except Exception as e:
            logger.error(f"Tidal init failed: {e}")
            return False

    def _init_deezer(self):
        if not DEEZER_AVAILABLE: return False
        if self.deezer_client: return True

        try:
            arl = self.config['deezer'].get('arl')
            headers = {}
            if arl:
                headers = {'Cookie': f'arl={arl}'}

            self.deezer_client = deezer.Client(headers=headers)
            return True
        except Exception as e:
            logger.error(f"Deezer init failed: {e}")
            return False

    def search_tidal(self, query, limit=5):
        """Search Tidal. Returns list of dicts with metadata and obj."""
        if not self._init_tidal(): return []

        candidates = []
        try:
            # Attempt search
            results = self.tidal_session.search(query, models=[tidalapi.Track], limit=limit)

            for track in results['tracks'][:limit]:
                # Extract Cover Art URL (if available)
                cover_url = None
                if hasattr(track, 'album') and track.album and hasattr(track.album, 'cover'):
                     # Tidal cover logic often requires constructing URL or accessing property
                     # Assuming standard tidal method or property
                     try:
                         # tidalapi 0.7+: album.image(80) or similar.
                         # fallback to manually constructing from cover_id
                         if hasattr(track.album, 'image'):
                             cover_url = track.album.image(320)
                         elif hasattr(track.album, 'cover'):
                             # cover is usually a UUID like ID.
                             # URL format: https://resources.tidal.com/images/{id.replace('-', '/')}/320x320.jpg
                             cover_id = track.album.cover
                             if cover_id:
                                 path = cover_id.replace('-', '/')
                                 cover_url = f"https://resources.tidal.com/images/{path}/320x320.jpg"
                     except: pass

                candidates.append({
                    'source': 'Tidal',
                    'title': track.name,
                    'artist': track.artist.name if track.artist else "Unknown",
                    'album': track.album.name if track.album else "Unknown",
                    'duration': track.duration if hasattr(track, 'duration') else 0,
                    'cover_url': cover_url,
                    'obj': track
                })

        except Exception as e:
            logger.error(f"Tidal search error: {e}")
        return candidates

    def expand_artist(self, artist_name):
        """Expand artist into a list of tracks (Top Tracks)."""
        tracks = []
        if self._init_tidal():
            try:
                search = self.tidal_session.search(artist_name, models=[tidalapi.Artist])
                if search['artists']:
                    artist = search['artists'][0]
                    top_tracks = artist.get_top_tracks() # Helper method on Artist object
                    tracks = [f"{t.artist.name} - {t.name}" for t in top_tracks]
                    logger.info(f"Expanded Artist '{artist_name}' via Tidal: {len(tracks)} tracks")
            except Exception as e:
                logger.error(f"Tidal artist expansion failed: {e}")

        if not tracks and self._init_deezer():
            try:
                # Deezer: Use specialized search methods
                # First find artist
                artists = self.deezer_client.search_artists(artist_name)
                if artists:
                    artist = artists[0]
                    top_tracks = artist.get_top()
                    tracks = [f"{t.artist.name} - {t.title}" for t in top_tracks]
                    logger.info(f"Expanded Artist '{artist_name}' via Deezer: {len(tracks)} tracks")
            except Exception as e:
                logger.error(f"Deezer artist expansion failed: {e}")
        return tracks

    def expand_album(self, album_name):
        """Expand album into a list of tracks."""
        tracks = []
        if self._init_tidal():
            try:
                search = self.tidal_session.search(album_name, models=[tidalapi.Album])
                if search['albums']:
                    album = search['albums'][0]
                    # Fetch tracks for album
                    album_tracks = album.tracks()
                    tracks = [f"{t.artist.name} - {t.name}" for t in album_tracks]
                    logger.info(f"Expanded Album '{album_name}' via Tidal: {len(tracks)} tracks")
            except Exception as e:
                logger.error(f"Tidal album expansion failed: {e}")

        if not tracks and self._init_deezer():
            try:
                # Deezer search albums
                albums = self.deezer_client.search_albums(album_name)
                if albums:
                    album = albums[0]
                    album_tracks = album.get_tracks()
                    tracks = [f"{t.artist.name} - {t.title}" for t in album_tracks]
                    logger.info(f"Expanded Album '{album_name}' via Deezer: {len(tracks)} tracks")
            except Exception as e:
                logger.error(f"Deezer album expansion failed: {e}")
        return tracks

    def download_tidal(self, track, output_path):
        """Download track from Tidal."""
        if not track: return None

        try:
            logger.info(f"Attempting to download Tidal track {track.name}")
            if self.tidal_session:
                try:
                    # Check method existence
                    if hasattr(self.tidal_session.track, 'get_url'):
                        stream_url = self.tidal_session.track.get_url(track.id)
                    elif hasattr(self.tidal_session.track, 'get_stream_url'):
                        stream_url = self.tidal_session.track.get_stream_url(track.id)
                    elif hasattr(track, 'get_url'):
                        stream_url = track.get_url()
                    else:
                        # Some versions use direct track object
                        stream_url = self.tidal_session.track(track.id).get_url()

                    if stream_url:
                        response = requests.get(stream_url, stream=True)
                        if response.status_code == 200:
                            with open(output_path, 'wb') as f:
                                for chunk in response.iter_content(chunk_size=1024):
                                    f.write(chunk)
                            logger.info(f"Downloaded Tidal track to {output_path}")
                            return output_path
                        with open(output_path, 'wb') as f:
                            for chunk in response.iter_content(chunk_size=1024):
                                f.write(chunk)
                        logger.info(f"Downloaded Tidal track to {output_path}")
                        return output_path
                    else:
                        logger.error(f"Tidal stream request failed: {response.status_code}")
                except Exception as stream_e:
                    logger.error(f"Tidal get_url failed: {stream_e}")

            logger.error("Tidal download failed: No valid stream URL.")
            return None
        except Exception as e:
            logger.error(f"Tidal download failed: {e}")
            return None

    def search_deezer(self, query, limit=5):
        """Search Deezer. Returns list of dicts."""
        if not self._init_deezer(): return []

        candidates = []
        try:
            if hasattr(self.deezer_client, 'search_tracks'):
                results = self.deezer_client.search_tracks(query, limit=limit)
            else:
                results = self.deezer_client.search(query, limit=limit)

            for track in results[:limit]:
                # Extract Cover
                cover_url = None
                if hasattr(track, 'album') and hasattr(track.album, 'cover_medium'):
                    cover_url = track.album.cover_medium

                candidates.append({
                    'source': 'Deezer',
                    'title': track.title,
                    'artist': track.artist.name if hasattr(track, 'artist') else "Unknown",
                    'album': track.album.title if hasattr(track, 'album') else "Unknown",
                    'duration': track.duration if hasattr(track, 'duration') else 0,
                    'cover_url': cover_url,
                    'obj': track
                })
        except Exception as e:
            logger.error(f"Deezer search error: {e}")
        return candidates

    def download_deezer(self, track, output_path):
        """Download from Deezer."""
        if not track: return None
        try:
            logger.info(f"Attempting to download Deezer track {track.title}")
            # Real implementation requires authenticated client with ARL
            # Placeholder for potential library method:
            # stream_url = self.deezer_client.get_track_download_url(track.id)

            logger.error("Deezer download failed: Client not authenticated or method unavailable.")
            return None
        except Exception as e:
            logger.error(f"Deezer download failed: {e}")
            return None

    def search_youtube_video(self, query, limit=5):
        """Search YouTube. Returns list of dicts."""
        if not YT_DLP_AVAILABLE: return []

        # 'extract_flat': 'in_playlist' allows getting metadata for search results without deep extraction
        # but 'extract_flat': True might be too shallow for some thumbnails.
        # We'll use 'extract_flat': 'in_playlist' which is safer for search queries.
        ydl_opts = {
            'quiet': True,
            'default_search': f'ytsearch{limit}',
            'noplaylist': True,
            'extract_flat': 'in_playlist',
            'skip_download': True,
            'ignoreerrors': True,
        }

        candidates = []
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(f"{query} Official Music Video", download=False)

                entries = info.get('entries', [])
                if not entries and 'entries' not in info:
                     # Sometimes info IS the result if single match? Unlikely for ytsearch
                     entries = [info]

                for vid in entries:
                    if not vid: continue
                    # For flat extraction, thumbnails might be missing or limited
                    # We accept what we get.
                    candidates.append({
                        'source': 'YouTube',
                        'title': vid.get('title', 'Unknown'),
                        'artist': vid.get('uploader', 'Unknown'),
                        'album': 'N/A',
                        'duration': vid.get('duration', 0),
                        'cover_url': vid.get('thumbnail') or vid.get('thumbnails', [{}])[-1].get('url'),
                        'obj': vid
                    })
        except Exception as e:
            logger.error(f"YouTube search failed: {e}")
        return candidates

    def download_youtube_video(self, video_info, output_path):
        """Download YouTube video."""
        if not video_info: return None

        ydl_opts = {
            'quiet': True,
            'outtmpl': output_path, # Ensure this matches desired format
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'noplaylist': True
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([video_info['webpage_url']])
            return output_path
        except Exception as e:
            logger.error(f"YouTube download failed: {e}")
            return None

    def search_soulseek(self, query, limit=5):
        """Search Soulseek via Slskd API."""
        if not self.config.get('soulseek', {}).get('enabled'): return []

        url = self.config['soulseek'].get('url', 'http://localhost:5030')
        api_key = self.config['soulseek'].get('api_key', '')

        # Placeholder for Slskd logic
        # 1. POST /api/v0/search {searchText: query} -> get id
        # 2. GET /api/v0/search/{id} -> poll results
        # For this exercise, since we can't test against a real instance easily, return empty or mock
        return []

    def download_soulseek(self, track_obj, output_path):
        """Download from Soulseek."""
        # This requires queuing a download in slskd and monitoring it.
        # Then moving the file to output_path.
        pass

    def parse_spotify_url(self, url):
        """Parse Spotify URL to get Artist/Track info."""
        try:
            response = requests.get(url)
            if response.status_code == 200:
                html = response.text
                # Regex for <title>Content</title>
                match = re.search(r'<title>(.*?)</title>', html)
                if match:
                    title_text = match.group(1)
                    title_text = title_text.replace(" | Spotify", "")
                    parts = title_text.split(" - ")
                    if len(parts) >= 2:
                        return {'title': parts[0], 'artist': parts[1]}
                    else:
                        return {'title': title_text, 'artist': 'Unknown'}
        except Exception as e:
            logger.error(f"Spotify parse failed: {e}")
        return None

    def parse_spotify_playlist(self, url):
        """Parse Spotify Playlist URL to get list of tracks."""
        tracks = []
        try:
            response = requests.get(url)
            if response.status_code == 200:
                html = response.text

                # Regex for "name":"Song Name","artists":[{"name":"Artist"
                matches = re.findall(r'"name":"(.*?)","artists":\[{"name":"(.*?)"', html)
                for song, artist in matches:
                     if song and artist:
                         tracks.append(f"{artist} - {song}")

                if not tracks:
                    meta = self.parse_spotify_url(url)
                    if meta:
                         # Single track or album fallback
                         pass
        except Exception as e:
            logger.error(f"Spotify playlist parse failed: {e}")
        return list(set(tracks)) # Unique

    def get_musicbrainz_metadata(self, query):
        """Search MusicBrainz for metadata."""
        if not MUSICBRAINZ_AVAILABLE: return None

        try:
            result = musicbrainzngs.search_recordings(query=query, limit=1)
            if result['recording-list']:
                rec = result['recording-list'][0]
                return {
                    'title': rec['title'],
                    'artist': rec['artist-credit'][0]['name'],
                    'album': rec['release-list'][0]['title'] if 'release-list' in rec else 'Unknown',
                    'date': rec['date'] if 'date' in rec else '0000'
                }
        except Exception as e:
            logger.error(f"MusicBrainz search failed: {e}")
        return None
