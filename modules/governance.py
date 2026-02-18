import os
import shutil
import re
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

class Governance:
    def __init__(self, config):
        self.config = config
        self.music_base = Path(config['paths']['music_dir'])
        self.video_base = Path(config['paths']['video_dir'])

        # Create dirs
        self.music_base.mkdir(parents=True, exist_ok=True)
        self.video_base.mkdir(parents=True, exist_ok=True)

    def sanitize(self, name):
        """Sanitize filename components."""
        if not name: return "Unknown"
        name = re.sub(r'[\\/*?:"<>|]', "", str(name))
        name = re.sub(r'\s+', ' ', name).strip()
        name = name.strip('.')
        return name if name else "Unknown"

    def get_music_path(self, metadata, ext):
        """Generate archival path for audio."""
        artist = self.sanitize(metadata.get('artist'))
        title = self.sanitize(metadata.get('title'))
        album = self.sanitize(metadata.get('album'))

        # Year extraction
        date = str(metadata.get('date', '0000'))
        year = date[:4] if len(date) >= 4 else "0000"

        # Structure: Music/Artist/Album [Year]/Artist - Title.ext
        folder = self.music_base / artist / f"{album} [{year}]"
        filename = f"{artist} - {title}{ext}"
        return folder / filename

    def get_video_path(self, metadata, ext):
        """Generate archival path for video."""
        artist = self.sanitize(metadata.get('artist'))
        title = self.sanitize(metadata.get('title'))

        # Structure: Music Videos/Artist - Title.ext
        filename = f"{artist} - {title}{ext}"
        return self.video_base / filename

    def archive_audio(self, src_path, metadata):
        """Move audio and LRC to final destination."""
        if not os.path.exists(src_path): return None

        dest = self.get_music_path(metadata, Path(src_path).suffix)
        dest.parent.mkdir(parents=True, exist_ok=True)

        try:
            shutil.move(src_path, dest)
            logger.info(f"Archived Audio: {dest}")

            # Move LRC if exists
            lrc_src = Path(src_path).with_suffix('.lrc')
            if lrc_src.exists():
                lrc_dest = dest.with_suffix('.lrc')
                shutil.move(lrc_src, lrc_dest)

            return str(dest)
        except Exception as e:
            logger.error(f"Archive Audio Failed: {e}")
            return None

    def archive_video(self, src_path, metadata):
        """Move video and SRT to final destination."""
        if not os.path.exists(src_path): return None

        dest = self.get_video_path(metadata, Path(src_path).suffix)
        dest.parent.mkdir(parents=True, exist_ok=True)

        try:
            shutil.move(src_path, dest)
            logger.info(f"Archived Video: {dest}")

            # Move SRT if exists
            srt_src = Path(src_path).with_suffix('.srt')
            if srt_src.exists():
                srt_dest = dest.with_suffix('.srt')
                shutil.move(srt_src, srt_dest)

            return str(dest)
        except Exception as e:
            logger.error(f"Archive Video Failed: {e}")
            return None

    def check_exists(self, metadata, file_type='audio'):
        """Check if final file already exists."""
        if file_type == 'audio':
            # Check common extensions
            for ext in ['.flac', '.mp3', '.m4a']:
                path = self.get_music_path(metadata, ext)
                if path.exists(): return str(path)
        elif file_type == 'video':
            for ext in ['.mp4', '.mkv', '.webm']:
                path = self.get_video_path(metadata, ext)
                if path.exists(): return str(path)
        return None

if __name__ == "__main__":
    import argparse
    import yaml

    try:
        with open("config.yaml", "r") as f:
            config = yaml.safe_load(f)
    except FileNotFoundError:
        config = {'paths': {'music_dir': 'Output/Music', 'video_dir': 'Output/Music Videos'}}
        print("Warning: config.yaml not found, using default config.")

    parser = argparse.ArgumentParser(description="Governance Module CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Archive Audio
    p_audio = subparsers.add_parser("archive_audio")
    p_audio.add_argument("file", help="Input file path")
    p_audio.add_argument("--artist", required=True)
    p_audio.add_argument("--title", required=True)
    p_audio.add_argument("--album", required=True)
    p_audio.add_argument("--date", default="2023")

    # Archive Video
    p_video = subparsers.add_parser("archive_video")
    p_video.add_argument("file", help="Input file path")
    p_video.add_argument("--artist", required=True)
    p_video.add_argument("--title", required=True)

    args = parser.parse_args()
    gov = Governance(config)

    meta = {'artist': args.artist, 'title': args.title}
    if hasattr(args, 'album'): meta['album'] = args.album
    if hasattr(args, 'date'): meta['date'] = args.date

    if args.command == "archive_audio":
        res = gov.archive_audio(args.file, meta)
        print(f"Archived Audio: {res}")

    elif args.command == "archive_video":
        res = gov.archive_video(args.file, meta)
        print(f"Archived Video: {res}")
