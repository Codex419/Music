import os
import math
import logging
from pathlib import Path

# Try importing dependencies
try:
    from faster_whisper import WhisperModel
    FASTER_WHISPER_AVAILABLE = True
except ImportError:
    FASTER_WHISPER_AVAILABLE = False
    print("Warning: faster_whisper not found. Transcription disabled.")

try:
    import mutagen
    from mutagen.flac import FLAC, Picture
    from mutagen.mp4 import MP4, MP4Cover
    from mutagen.id3 import ID3, USLT
    MUTAGEN_AVAILABLE = True
except ImportError:
    MUTAGEN_AVAILABLE = False
    print("Warning: mutagen not found. Metadata operations disabled.")

logger = logging.getLogger(__name__)

class Enrichment:
    def __init__(self, config):
        self.config = config
        self.model = None
        self.model_size = config['ai'].get('model_size', 'small')
        self.device = config['ai'].get('device', 'cpu')
        self.compute_type = config['ai'].get('precision', 'int8')

    def _load_model(self):
        if not FASTER_WHISPER_AVAILABLE:
            raise ImportError("faster_whisper is not installed.")

        if self.model is None:
            logger.info(f"Loading Whisper model: {self.model_size} on {self.device}")
            try:
                self.model = WhisperModel(self.model_size, device=self.device, compute_type=self.compute_type)
            except Exception as e:
                logger.error(f"Failed to load Whisper model: {e}")
                raise

    def format_timestamp_lrc(self, seconds):
        """Format seconds to [mm:ss.xx] for LRC."""
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        hundredths = int((seconds - int(seconds)) * 100)
        return f"[{minutes:02d}:{secs:02d}.{hundredths:02d}]"

    def format_timestamp_srt(self, seconds):
        """Format seconds to hh:mm:ss,ms for SRT."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds - int(seconds)) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

    def transcribe_file(self, filepath: str, output_format: str = 'lrc') -> str:
        """
        Transcribe audio/video file.
        output_format: 'lrc' or 'srt'
        Returns path to generated file.
        """
        if not FASTER_WHISPER_AVAILABLE:
            logger.warning("Transcription skipped (faster_whisper missing).")
            return None

        self._load_model()

        segments, info = self.model.transcribe(
            filepath,
            beam_size=self.config['ai'].get('beam_size', 5),
            vad_filter=self.config['ai'].get('vad_filter', True)
        )

        output_path = Path(filepath).with_suffix(f'.{output_format}')

        with open(output_path, 'w', encoding='utf-8') as f:
            if output_format == 'lrc':
                for segment in segments:
                    timestamp = self.format_timestamp_lrc(segment.start)
                    text = segment.text.strip()
                    f.write(f"{timestamp}{text}\n")
            elif output_format == 'srt':
                for i, segment in enumerate(segments):
                    start = self.format_timestamp_srt(segment.start)
                    end = self.format_timestamp_srt(segment.end)
                    text = segment.text.strip()
                    f.write(f"{i+1}\n{start} --> {end}\n{text}\n\n")

        return str(output_path)

    def embed_lyrics(self, audio_path: str, lrc_path: str):
        """Embed LRC content into audio file metadata (FLAC/ID3)."""
        if not MUTAGEN_AVAILABLE: return

        try:
            with open(lrc_path, 'r', encoding='utf-8') as f:
                lyrics = f.read()

            audio = mutagen.File(audio_path)

            if isinstance(audio, FLAC):
                audio['LYRICS'] = lyrics
                audio.save()
            elif isinstance(audio, ID3): # MP3
                audio.add(USLT(encoding=3, lang='eng', desc='desc', text=lyrics))
                audio.save()
            # Add other formats if needed

        except Exception as e:
            logger.error(f"Failed to embed lyrics for {audio_path}: {e}")

    def sync_metadata(self, source_audio: str, target_video: str):
        """Copy metadata (Artist, Title, Album, Year, Cover Art) from audio to video."""
        if not MUTAGEN_AVAILABLE: return

        try:
            audio = mutagen.File(source_audio)
            video = MP4(target_video)

            if not audio or not video:
                logger.error("Could not load audio or video for metadata sync.")
                return

            # Map generic mutagen tags to MP4 specific tags
            # MP4 tags: \xa9ART (Artist), \xa9nam (Title), \xa9alb (Album), \xa9day (Year)

            # Helper to get first item safely
            def get_tag(obj, keys):
                for k in keys:
                    if k in obj:
                        val = obj[k]
                        return val[0] if isinstance(val, list) else val
                return None

            artist = get_tag(audio, ['artist', 'ARTIST', 'TPE1'])
            title = get_tag(audio, ['title', 'TITLE', 'TIT2'])
            album = get_tag(audio, ['album', 'ALBUM', 'TALB'])
            date = get_tag(audio, ['date', 'DATE', 'TDRC', 'TYER'])

            if artist: video['\xa9ART'] = artist
            if title: video['\xa9nam'] = title
            if album: video['\xa9alb'] = album
            if date: video['\xa9day'] = str(date)

            # Cover Art
            if isinstance(audio, FLAC) and audio.pictures:
                # Convert FLAC picture to MP4 cover
                pic = audio.pictures[0]
                video['covr'] = [MP4Cover(pic.data, imageformat=MP4Cover.FORMAT_JPEG if pic.mime == 'image/jpeg' else MP4Cover.FORMAT_PNG)]

            # TODO: Handle ID3 APIC frames for MP3 source

            video.save()
            logger.info(f" synced metadata from {source_audio} to {target_video}")

        except Exception as e:
            logger.error(f"Metadata sync failed: {e}")
