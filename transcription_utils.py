"""
Utility functions for formatting transcription segments.
"""
from faster_whisper.utils import format_timestamp # Ensure this import is available if used directly

def segments_to_srt(segments):
    """Converts whisper segments to SRT subtitle format."""
    srt_content = ""
    for i, segment in enumerate(segments):
        start_time = format_timestamp(segment.start, srt_format=True)
        end_time = format_timestamp(segment.end, srt_format=True)
        srt_content += f"{i + 1}\n{start_time} --> {end_time}\n{segment.text.strip()}\n\n"
    return srt_content

def segments_to_vtt(segments):
    """Converts whisper segments to VTT subtitle format."""
    vtt_content = "WEBVTT\n\n"
    for segment in segments:
        start_time = format_timestamp(segment.start, srt_format=False) # VTT uses . for ms
        end_time = format_timestamp(segment.end, srt_format=False)
        vtt_content += f"{start_time} --> {end_time}\n{segment.text.strip()}\n\n"
    return vtt_content

def segments_to_txt(segments):
    """Converts whisper segments to plain text format."""
    return "\n".join([segment.text.strip() for segment in segments])

def segments_to_lrc(segments):
    """Converts whisper segments to LRC (lyrics) format."""
    lrc_content = ""
    for segment in segments:
        minutes = int(segment.start // 60)
        seconds = int(segment.start % 60)
        hundredths = int((segment.start * 100) % 100) # Or use segment.start % 1 * 100 for precision
        lrc_content += f"[{minutes:02d}:{seconds:02d}.{hundredths:02d}]{segment.text.strip()}\n"
    return lrc_content

if __name__ == '__main__':
    # Example usage (requires mock Segment objects)
    class MockSegment:
        def __init__(self, start, end, text):
            self.start = start
            self.end = end
            self.text = text

    mock_segments = [
        MockSegment(0.0, 2.5, "Hello world."),
        MockSegment(2.5, 5.0, "This is a test.")
    ]
    print("--- SRT ---")
    print(segments_to_srt(mock_segments))
    print("--- VTT ---")
    print(segments_to_vtt(mock_segments))
    print("--- TXT ---")
    print(segments_to_txt(mock_segments))
    print("--- LRC ---")
    print(segments_to_lrc(mock_segments))
