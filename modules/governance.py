import os
import shutil
import re
from pathlib import Path

class Governance:
    def __init__(self, config):
        self.config = config
        self.music_base_path = Path(config['paths']['music_dir'])
        self.video_base_path = Path(config['paths']['video_dir'])

        # Ensure base directories exist
        self.music_base_path.mkdir(parents=True, exist_ok=True)
        self.video_base_path.mkdir(parents=True, exist_ok=True)

    def sanitize_filename(self, name: str) -> str:
        """Sanitize a string to be safe for filenames."""
        if not name:
            return "Unknown"
        # Remove invalid characters
        name = re.sub(r'[\\/*?:"<>|]', "", name)
        # Replace multiple spaces/dots
        name = re.sub(r'\s+', ' ', name).strip()
        name = re.sub(r'\.+', '.', name).strip('.')
        if not name:
            return "Unknown"
        return name

    def validate_metadata(self, metadata: dict) -> bool:
        """
        Validate that essential metadata is present.
        Required: artist, title, album, date (year).
        """
        required_keys = ['artist', 'title', 'album', 'date']
        for key in required_keys:
            if key not in metadata or not metadata[key]:
                return False
        return True

    def _get_year(self, date_str: str) -> str:
        """Extract 4-digit year from date string."""
        if not date_str:
            return "0000"
        match = re.search(r'\d{4}', str(date_str))
        return match.group(0) if match else "0000"

    def archive_audio(self, filepath: str, metadata: dict) -> str:
        """
        Move audio file and its accompanying .lrc file to the final structure:
        Music > Artist > Album [Release Year] > Artist - Song.Format
        """
        if not self.validate_metadata(metadata):
            raise ValueError(f"Invalid metadata for {filepath}: {metadata}")

        artist = self.sanitize_filename(metadata['artist'])
        album = self.sanitize_filename(metadata['album'])
        title = self.sanitize_filename(metadata['title'])
        year = self._get_year(metadata['date'])

        # Construct path: Music/Artist/Album [Year]/
        album_folder = f"{album} [{year}]"
        dest_dir = self.music_base_path / artist / album_folder
        dest_dir.mkdir(parents=True, exist_ok=True)

        # Construct filename: Artist - Song.ext
        ext = Path(filepath).suffix
        filename = f"{artist} - {title}{ext}"
        dest_path = dest_dir / filename

        # Move Audio File
        shutil.move(filepath, dest_path)

        # Check for and move .lrc file if it exists
        lrc_source = Path(filepath).with_suffix('.lrc')
        if lrc_source.exists():
            lrc_dest = dest_dir / f"{artist} - {title}.lrc"
            shutil.move(lrc_source, lrc_dest)

        return str(dest_path)

    def archive_video(self, filepath: str, metadata: dict) -> str:
        """
        Move video file and its accompanying .srt file to the final structure:
        Music Videos > Artist - Song.Format
        """
        if not self.validate_metadata(metadata):
            # Fallback if metadata is incomplete but we have Artist/Title from search
            if 'artist' not in metadata or 'title' not in metadata:
                 raise ValueError(f"Invalid metadata for {filepath}: {metadata}")

        artist = self.sanitize_filename(metadata['artist'])
        title = self.sanitize_filename(metadata['title'])

        # Construct filename: Artist - Song.ext
        ext = Path(filepath).suffix
        filename = f"{artist} - {title}{ext}"
        dest_path = self.video_base_path / filename

        # Move Video File
        shutil.move(filepath, dest_path)

        # Check for and move .srt file if it exists
        srt_source = Path(filepath).with_suffix('.srt')
        if srt_source.exists():
            srt_dest = self.video_base_path / f"{artist} - {title}.srt"
            shutil.move(srt_source, srt_dest)

        return str(dest_path)
