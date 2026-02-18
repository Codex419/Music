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

try:
    import mutagen
    from mutagen.flac import FLAC, Picture
    from mutagen.mp4 import MP4, MP4Cover, MP4Tags
    from mutagen.id3 import ID3, USLT, TPE1, TIT2, TALB, TDRC, TRCK, TPOS
    MUTAGEN_AVAILABLE = True
except ImportError:
    MUTAGEN_AVAILABLE = False

logger = logging.getLogger(__name__)

class Enrichment:
    def __init__(self, config):
        self.config = config
        self.model = None
        self.model_size = config['ai'].get('model_size', 'small')
        self.device = config['ai'].get('device', 'auto')
        self.compute_type = config['ai'].get('precision', 'int8')

        # Mapping from generic tags to MP4 atoms
        self.MP4_TAG_MAP = {
            'artist': '\xa9ART', 'title': '\xa9nam', 'album': '\xa9alb',
            'genre': '\xa9gen', 'date': '\xa9day', 'year': '\xa9day',
            'albumartist': 'aART', 'composer': '\xa9wrt', 'comment': '\xa9cmt'
        }

    def _load_model(self):
        if not FASTER_WHISPER_AVAILABLE:
            raise ImportError("faster_whisper is not installed.")

        if self.model is None:
            logger.info(f"Loading Whisper model: {self.model_size} ({self.device})")
            try:
                self.model = WhisperModel(self.model_size, device=self.device, compute_type=self.compute_type)
            except Exception as e:
                logger.error(f"Failed to load Whisper model: {e}")
                raise

    # --- Timestamps ---
    def format_lrc_timestamp(self, seconds):
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        hundredths = int((seconds - int(seconds)) * 100)
        return f"[{minutes:02d}:{secs:02d}.{hundredths:02d}]"

    def format_srt_timestamp(self, seconds):
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds - int(seconds)) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

    # --- Transcription ---
    def transcribe_file(self, filepath: str, output_format: str = 'lrc') -> str:
        """
        Transcribe audio/video.
        format: 'lrc' (audio) or 'srt' (video).
        Returns output path.
        """
        if not FASTER_WHISPER_AVAILABLE: return None
        if not os.path.exists(filepath): return None

        # Check existing
        output_path = Path(filepath).with_suffix(f'.{output_format}')
        if output_path.exists():
            logger.info(f"Transcription exists: {output_path}")
            return str(output_path)

        try:
            self._load_model()
            logger.info(f"Transcribing {filepath}...")

            segments, info = self.model.transcribe(
                filepath,
                beam_size=self.config['ai'].get('beam_size', 5),
                vad_filter=self.config['ai'].get('vad_filter', True)
            )

            with open(output_path, 'w', encoding='utf-8') as f:
                if output_format == 'lrc':
                    for segment in segments:
                        ts = self.format_lrc_timestamp(segment.start)
                        f.write(f"{ts}{segment.text.strip()}\n")
                elif output_format == 'srt':
                    for i, segment in enumerate(segments):
                        start = self.format_srt_timestamp(segment.start)
                        end = self.format_srt_timestamp(segment.end)
                        f.write(f"{i+1}\n{start} --> {end}\n{segment.text.strip()}\n\n")

            return str(output_path)
        except Exception as e:
            logger.error(f"Transcription failed for {filepath}: {e}")
            return None

    # --- Metadata Transfer (Robust Legacy Logic) ---
    def transfer_metadata(self, audio_path, video_path):
        """
        Transfers tags and cover art from Audio (FLAC/MP3) to Video (MP4).
        Adapted from legacy/Metadata.pyw
        """
        if not MUTAGEN_AVAILABLE: return False
        if not (os.path.exists(audio_path) and os.path.exists(video_path)): return False

        logger.info(f"Transferring metadata: {os.path.basename(audio_path)} -> {os.path.basename(video_path)}")

        try:
            audio = mutagen.File(audio_path, easy=False)
            if not audio: return False

            try:
                video = MP4(video_path)
                if video.tags is None: video.add_tags()
            except Exception: return False

            # Transfer Text Tags
            count = 0
            # Helper to extract value safely from various mutagen types
            def get_val(tags, keys):
                for k in keys:
                    if k in tags:
                        v = tags[k]
                        return v[0] if isinstance(v, list) else str(v)
                return None

            # Iterate generic map
            for name, mp4_key in self.MP4_TAG_MAP.items():
                val = None
                # Define possible keys in source
                if name == 'artist': keys = ['artist', 'TPE1', 'ARTIST']
                elif name == 'title': keys = ['title', 'TIT2', 'TITLE']
                elif name == 'album': keys = ['album', 'TALB', 'ALBUM']
                elif name == 'date': keys = ['date', 'year', 'TDRC', 'TYER', 'DATE']
                else: keys = [name, name.upper()]

                val = get_val(audio, keys)
                if val:
                    # Year formatting
                    if name == 'date': val = str(val)[:4]

                    video[mp4_key] = [val]
                    count += 1

            # Transfer Cover Art
            if isinstance(audio, FLAC) and audio.pictures:
                pic = audio.pictures[0]
                fmt = MP4Cover.FORMAT_JPEG if pic.mime == 'image/jpeg' else MP4Cover.FORMAT_PNG
                video['covr'] = [MP4Cover(pic.data, imageformat=fmt)]
                count += 1
            elif isinstance(audio, ID3):
                # MP3 APIC
                for key in audio.keys():
                    if key.startswith('APIC'):
                        pic = audio[key]
                        fmt = MP4Cover.FORMAT_JPEG if pic.mime == 'image/jpeg' else MP4Cover.FORMAT_PNG
                        video['covr'] = [MP4Cover(pic.data, imageformat=fmt)]
                        count += 1
                        break

            if count > 0:
                video.save()
                return True
            return False

        except Exception as e:
            logger.error(f"Metadata transfer error: {e}")
            return False

    def embed_lyrics(self, audio_path, lrc_path):
        """Embeds LRC into audio file."""
        if not MUTAGEN_AVAILABLE or not os.path.exists(lrc_path): return

        try:
            with open(lrc_path, 'r', encoding='utf-8') as f:
                lyrics = f.read()

            audio = mutagen.File(audio_path)
            if isinstance(audio, FLAC):
                audio['LYRICS'] = lyrics
                audio.save()
            elif isinstance(audio, ID3):
                audio.add(USLT(encoding=3, lang='eng', desc='desc', text=lyrics))
                audio.save()
        except Exception as e:
            logger.error(f"Embed lyrics failed: {e}")

if __name__ == "__main__":
    import argparse
    import yaml

    try:
        with open("config.yaml", "r") as f:
            config = yaml.safe_load(f)
    except FileNotFoundError:
        config = {'ai': {}}
        print("Warning: config.yaml not found, using empty config.")

    parser = argparse.ArgumentParser(description="Enrichment Module CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Transcribe
    p_trans = subparsers.add_parser("transcribe")
    p_trans.add_argument("file", help="Input file path")
    p_trans.add_argument("--format", choices=['lrc', 'srt'], default='lrc')

    # Transfer Metadata
    p_meta = subparsers.add_parser("transfer_metadata")
    p_meta.add_argument("audio", help="Source audio file")
    p_meta.add_argument("video", help="Target video file")

    args = parser.parse_args()
    enrichment = Enrichment(config)

    if args.command == "transcribe":
        if not os.path.exists(args.file):
            print(f"Error: File not found: {args.file}")
        else:
            res = enrichment.transcribe_file(args.file, args.format)
            print(f"Transcription result: {res}")

    elif args.command == "transfer_metadata":
        if enrichment.transfer_metadata(args.audio, args.video):
            print("Metadata transfer successful.")
        else:
            print("Metadata transfer failed.")
