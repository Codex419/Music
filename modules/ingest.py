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
        if self.tidal_session: return True

        try:
            # Initialize Session with config if available
            config = tidalapi.Config()
            if self.config['tidal'].get('quality'):
                # Map config quality to tidalapi Quality enum or string
                # This is approximate
                pass

            self.tidal_session = tidalapi.Session(config=config)

            token = self.config['tidal'].get('token')
            client_id = self.config['tidal'].get('client_id')
            client_secret = self.config['tidal'].get('client_secret')

            # If explicit credentials provided, potentially used for login
            # Real tidalapi usually uses load_oauth_session with token details
            if token and client_id and client_secret:
                # Placeholder for loading session
                # self.tidal_session.load_oauth_session(token_type, access_token, refresh_token, expiry_time)
                pass

            return True
        except Exception as e:
            logger.error(f"Tidal init failed: {e}")
            return False

    def _init_deezer(self):
        if not DEEZER_AVAILABLE: return False
        if self.deezer_client: return True

        try:
            self.deezer_client = deezer.Client()
            arl = self.config['deezer'].get('arl')
            # deezer-python might not support ARL directly in Client init
            # We'd likely need a custom session or wrapper
            return True
        except Exception as e:
            logger.error(f"Deezer init failed: {e}")
            return False

    def search_tidal(self, query):
        """Search Tidal for a track. Returns track object or None."""
        if not self._init_tidal(): return None

        try:
            # Updated: tidalapi.media might not exist or models arg changed.
            # Using standard search pattern for recent tidalapi versions
            # tidalapi 0.7+ usually exposes models at top level or via session
            # We use string 'track' or imported model class
            results = self.tidal_session.search(query, models=[tidalapi.Track])
            if results['tracks']:
                return results['tracks'][0]
        except Exception as e:
            logger.error(f"Tidal search error: {e}")
        return None

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
            # Try to fetch real stream URL (requires valid session)
            if self.tidal_session:
                try:
                    # Note: method names might vary by tidalapi version
                    stream_url = self.tidal_session.track.get_url(track.id, audio_quality=self.config['tidal'].get('quality', 'HI_RES'))
                    response = requests.get(stream_url, stream=True)
                    if response.status_code == 200:
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

    def search_deezer(self, query):
        """Search Deezer for a track."""
        if not self._init_deezer(): return None

        try:
            # Use search() with default params, filter results manually if needed
            # or use search_tracks specifically if available
            if hasattr(self.deezer_client, 'search_tracks'):
                results = self.deezer_client.search_tracks(query)
            else:
                results = self.deezer_client.search(query)

            if results:
                return results[0]
        except Exception as e:
            logger.error(f"Deezer search error: {e}")
        return None

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

    def search_youtube_video(self, query):
        """Search YouTube for a Music Video."""
        if not YT_DLP_AVAILABLE: return None

        ydl_opts = {
            'quiet': True,
            'default_search': 'ytsearch1',
            'noplaylist': True,
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(f"{query} Official Music Video", download=False)
                if 'entries' in info and info['entries']:
                    return info['entries'][0] # Return video info dict
        except Exception as e:
            logger.error(f"YouTube search failed: {e}")
        return None

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
