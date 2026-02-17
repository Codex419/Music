import os
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
import mutagen
# Specific format classes for type checking if needed
from mutagen.id3 import ID3, TRCK, TPOS, TDRC, TYER, TDOR, TCON, TALB, TPE1, TPE2, TIT2, TCMP, TCOM, COMM # Add more ID3 frames if needed
from mutagen.flac import FLAC, Picture, FLACNoHeaderError # Explicitly import FLACNoHeaderError
from mutagen.mp4 import MP4, MP4Tags, MP4Cover # Added MP4Cover for potential future use
from mutagen.id3 import ID3NoHeaderError # Explicitly import ID3NoHeaderError
# OggVorbisNoHeaderError removed based on previous feedback
import threading
import queue # For thread-safe GUI updates
import traceback # For detailed error logging

# --- Configuration (Defaults, can be changed via GUI) ---
# List of audio file extensions to search for
AUDIO_EXTENSIONS = ['.mp3', '.flac', '.m4a', '.aac', '.ogg', '.opus', '.aiff', '.wav'] # Add more if needed

# --- Metadata Mapping ---
# Map common metadata keys (lowercased) from various audio formats
# to the standard MP4 atom keys used by mutagen.
METADATA_MAP_TO_MP4 = {
    # Standard Keys (try these first)
    'artist':       '\xa9ART', # Artist
    'title':        '\xa9nam', # Title / Name
    'album':        '\xa9alb', # Album
    'genre':        '\xa9gen', # Genre
    'date':         '\xa9day', # Year (or full date) - MP4 usually expects YYYY or YYYY-MM-DD
    'year':         '\xa9day', # Alias for date
    'albumartist':  'aART',    # Album Artist
    'tracknumber':  'trkn',    # Track Number (tuple: (track, total_tracks))
    'discnumber':   'disk',    # Disc Number (tuple: (disc, total_discs))
    'compilation':  'cpil',    # Part of a compilation (Boolean)
    'composer':     '\xa9wrt', # Composer
    'comment':      '\xa9cmt', # Comment
    # Add more mappings if you need them, e.g., lyrics, grouping etc.
    # 'lyrics':       '\xa9lyr',
    # 'grouping':     '\xa9grp',
    # 'albumart':     'covr' # For potential future use
}

# --- Core Logic Functions (Adapted for GUI Logging) ---

# Queue for sending log messages from the worker thread to the GUI thread
log_queue = queue.Queue()

def log_message(message):
    """Puts a message into the queue for the GUI to display."""
    log_queue.put(message)

def parse_mp4_filename(filename):
    """
    Parses 'Artist - Song Title.mp4' format.
    Returns (artist, title) or (None, None) if parsing fails.
    Logs errors via log_message.
    """
    try:
        base_name = os.path.splitext(filename)[0]
        parts = base_name.rsplit(' - ', 1)
        if len(parts) == 2:
            artist = parts[0].strip()
            title = parts[1].strip()
            if artist and title:
                return artist, title
    except Exception as e:
        log_message(f"   ⚠️ Error parsing filename '{filename}': {e}")
    return None, None

def find_matching_audio_file(target_artist, target_title, audio_root_dir):
    """
    Recursively searches the audio_root_dir for an audio file matching
    the target artist and title in its metadata. Returns the full path
    to the first match found, or None. Logs progress and results.
    """
    log_message(f"   🔍 Searching for audio match for '{target_artist} - {target_title}' in '{audio_root_dir}'...")
    target_artist_lower = target_artist.lower()
    target_title_lower = target_title.lower()

    for root, _, files in os.walk(audio_root_dir):
        for filename in files:
            _, ext = os.path.splitext(filename)
            if ext.lower() not in AUDIO_EXTENSIONS:
                continue

            audio_path = os.path.join(root, filename)
            try:
                # Attempt to load the file to read metadata
                audio_tags = mutagen.File(audio_path, easy=False)
                if not audio_tags:
                    continue # Skip if tags can't be read at all

                # --- Extract artist and title robustly ---
                current_artist = None
                current_title = None

                # <<< MODIFICATION START: Wrap tag access in try/except ValueError >>>
                try:
                    # Prioritize specific tags based on format (example for ID3)
                    if isinstance(audio_tags, ID3):
                        artist_frame = audio_tags.get('TPE1') # Artist
                        title_frame = audio_tags.get('TIT2')  # Title
                        if artist_frame and artist_frame.text: current_artist = str(artist_frame.text[0]).lower().strip()
                        if title_frame and title_frame.text: current_title = str(title_frame.text[0]).lower().strip()

                    # Fallback to common dictionary keys if specific frames aren't found or format is different
                    # Check if audio_tags is a dict-like object before using .get()
                    # Use direct key access within the try block, as .get() was causing issues
                    elif hasattr(audio_tags, '__contains__'): # Check if it behaves like a dictionary
                        if current_artist is None and 'artist' in audio_tags:
                            artist_list = audio_tags['artist'] # Try direct access
                            if artist_list: current_artist = str(artist_list[0]).lower().strip()
                        elif current_artist is None and 'ARTIST' in audio_tags: # Try uppercase
                             artist_list = audio_tags['ARTIST']
                             if artist_list: current_artist = str(artist_list[0]).lower().strip()

                        if current_title is None and 'title' in audio_tags:
                            title_list = audio_tags['title'] # Try direct access
                            if title_list: current_title = str(title_list[0]).lower().strip()
                        elif current_title is None and 'TITLE' in audio_tags: # Try uppercase
                            title_list = audio_tags['TITLE']
                            if title_list: current_title = str(title_list[0]).lower().strip()

                except ValueError as ve:
                    # This specifically catches the ValueError from _vorbis.py during tag access
                    log_message(f"      ⚠️ ValueError accessing tags in {os.path.basename(audio_path)}. Skipping file. Error: {ve}")
                    # log_message(f"         Traceback: {traceback.format_exc()}") # Keep traceback if needed for deeper debug
                    continue # Skip this file due to tag access error
                # <<< MODIFICATION END >>>


                # --- Comparison ---
                if current_artist == target_artist_lower and current_title == target_title_lower:
                    log_message(f"   ✅ Found potential match: {audio_path}")
                    return audio_path

            except (ID3NoHeaderError, FLACNoHeaderError) as e:
                # Expected errors for non-tagged files or header issues, ignore silently
                continue
            except mutagen.MutagenError as e:
                # Catch other specific Mutagen errors during file loading/parsing
                log_message(f"      ⚠️ Mutagen Warning reading {os.path.basename(audio_path)}: {e}")
                log_message(f"         Type: {type(e).__name__}")
                continue # Skip this file
            except Exception as e:
                # Catch and log traceback for other unexpected errors during file loading
                log_message(f"      ❌ Unexpected Error loading/processing {audio_path}: {e}")
                log_message(f"         Type: {type(e).__name__}")
                log_message(f"         Traceback: {traceback.format_exc()}")
                continue # Skip this file and continue searching

    log_message(f"   ❌ No audio match found for '{target_artist} - {target_title}'.")
    return None

def transfer_metadata(audio_path, mp4_path):
    """
    Reads metadata from the audio file and writes it to the MP4 file.
    Returns True on success, False on failure. Logs progress and results.
    Includes detailed error logging.
    """
    log_message(f"   🔄 Attempting transfer: '{os.path.basename(audio_path)}' -> '{os.path.basename(mp4_path)}'...")
    tags_transferred_count = 0
    mp4_file = None # Initialize mp4_file

    try:
        # --- Read Source Audio Metadata ---
        # Use easy=False for detailed objects, handle potential load errors here too
        try:
            audio_tags = mutagen.File(audio_path, easy=False)
            if not audio_tags:
                log_message(f"   ❌ Error: Could not read audio tags from '{audio_path}' (mutagen returned None). Skipping.")
                return False
        except Exception as load_err:
             # Catch errors during the initial mutagen.File() call itself
             log_message(f"   ❌ Error: Failed to load audio file '{audio_path}' with Mutagen: {load_err}")
             log_message(f"      Type: {type(load_err).__name__}")
             log_message(f"      Traceback: {traceback.format_exc()}")
             return False


        # --- Read or Create MP4 Tags ---
        try:
            mp4_file = MP4(mp4_path)
            if mp4_file.tags is None:
                log_message(f"      ℹ️ No existing tags found in MP4. Creating new tags...")
                mp4_file.add_tags()
                # Reload the file to ensure the tags object is accessible
                mp4_file = MP4(mp4_path)
                if mp4_file.tags is None:
                     raise mutagen.MutagenError("Failed to create MP4 tags object after add_tags().")
            # else: log_message("      ℹ️ Existing MP4 tags found.")

        except Exception as e:
             log_message(f"   ❌ Error: Could not open or initialize tags for MP4 '{mp4_path}': {e}")
             log_message(f"      Type: {type(e).__name__}")
             log_message(f"      Traceback: {traceback.format_exc()}")
             return False # Cannot proceed without MP4 tags object

        # --- Metadata Transfer Loop ---
        for common_key, mp4_key in METADATA_MAP_TO_MP4.items():
            source_value_obj = None # The raw object/value from the source tag

            # --- Find Source Value (More Robustly) ---
            possible_keys = []
            # Define potential keys for this common concept across formats
            if common_key == 'artist': possible_keys = ['artist', 'TPE1', '\xa9ART', 'Artist']
            elif common_key == 'title': possible_keys = ['title', 'TIT2', '\xa9nam', 'Title']
            elif common_key == 'album': possible_keys = ['album', 'TALB', '\xa9alb', 'Album']
            elif common_key == 'genre': possible_keys = ['genre', 'TCON', '\xa9gen', 'Genre']
            elif common_key == 'year': possible_keys = ['date', 'year', 'TDRC', 'TYER', 'TDOR', '\xa9day', 'Date', 'Year', 'Originalyear'] # TDRC (ID3v2.4+) is preferred for year
            elif common_key == 'albumartist': possible_keys = ['albumartist', 'TPE2', 'aART', 'Album Artist']
            elif common_key == 'tracknumber': possible_keys = ['tracknumber', 'TRCK', 'trkn']
            elif common_key == 'discnumber': possible_keys = ['discnumber', 'TPOS', 'disk']
            elif common_key == 'compilation': possible_keys = ['compilation', 'TCMP', 'cpil']
            elif common_key == 'composer': possible_keys = ['composer', 'TCOM', '\xa9wrt', 'Composer']
            elif common_key == 'comment': possible_keys = ['comment', 'COMM::eng', 'COMM', '\xa9cmt']

            # Add the mp4 key itself and the simple common key as fallbacks
            possible_keys.extend([mp4_key, common_key, common_key.upper(), common_key.capitalize()])

            # Iterate through possible keys to find the value in the source tags
            # Check if audio_tags supports 'in' operator (is dict-like)
            # Use try-except for tag access here as well, as ValueError might occur
            if hasattr(audio_tags, '__contains__'):
                 try:
                    for key in set(possible_keys): # Use set to avoid duplicates
                        if key in audio_tags:
                            source_value_obj = audio_tags[key] # Direct access might raise ValueError
                            # log_message(f"      Found source '{common_key}' using key '{key}': {source_value_obj}") # Debug
                            break # Found the value, stop searching keys for this common_key
                 except ValueError as ve:
                      log_message(f"      ⚠️ ValueError accessing source tag '{common_key}' (key: {key}) in {os.path.basename(audio_path)}. Skipping tag. Error: {ve}")
                      source_value_obj = None # Ensure we skip processing this tag
                 except Exception as e_access:
                      log_message(f"      ⚠️ Error accessing source tag '{common_key}' (key: {key}) in {os.path.basename(audio_path)}. Skipping tag. Error: {e_access}")
                      source_value_obj = None # Ensure we skip processing this tag


            # --- Process and Format Value for MP4 ---
            if source_value_obj is not None:
                value_to_write = None # This will hold the final formatted value for the MP4 tag
                try:
                    # --- Data Type Handling for MP4 ---
                    processed_value = source_value_obj
                    # Handle list values from source (take the first element)
                    if isinstance(processed_value, list) and len(processed_value) > 0:
                         processed_value = processed_value[0]

                    # --- Specific MP4 Tag Formatting ---
                    if mp4_key in ['trkn', 'disk']: # Track/Disc Number -> list containing [(num, total)]
                        num, total = 0, 0
                        text_value = ""
                        # Extract string value first, handling specific mutagen objects
                        if isinstance(processed_value, (TRCK, TPOS)): # Handle ID3 Frame Objects
                             text_value = str(processed_value.text[0]) if processed_value.text else "0"
                        else: # Handle plain strings or numbers
                             text_value = str(processed_value)
                        # Parse the string value
                        try:
                            if '/' in text_value:
                               parts = text_value.split('/', 1)
                               num = int(parts[0]) if parts[0] else 0
                               total = int(parts[1]) if parts[1] else 0
                            else:
                               num = int(text_value) if text_value else 0
                        except (ValueError, TypeError):
                            log_message(f"      ⚠️ Warn: Could not parse '{common_key}' value '{text_value}' into (num, total). Setting num only.")
                            try: num = int(text_value)
                            except: num = 0
                        value_to_write = [(num, total)]

                    elif mp4_key == 'cpil': # Compilation -> list containing [boolean]
                        bool_val = False
                        try:
                            if isinstance(processed_value, TCMP):
                                bool_val = (processed_value.text[0] == '1') if processed_value.text else False
                            else:
                                bool_val = bool(int(str(processed_value)))
                        except (ValueError, TypeError, IndexError):
                             log_message(f"      ⚠️ Warn: Could not parse compilation flag '{processed_value}'. Defaulting to False.")
                        value_to_write = [bool_val]

                    elif mp4_key == '\xa9day': # Year/Date -> list containing [string "YYYY"]
                        year_str = ""
                        try:
                            # Handle ID3 date frames (TDRC, TYER, TDOR)
                            if isinstance(processed_value, (TDRC, TYER, TDOR)):
                                # TDRC (YYYY-MM-DD...) is preferred, TYER (YYYY), TDOR (YYYY)
                                year_str = str(processed_value.text[0])[:4] if processed_value.text else ""
                            else: # Handle simple string/number
                                year_str = str(processed_value).strip()[:4] # Take first 4 non-whitespace chars

                            # Basic validation if we got a string
                            if year_str and len(year_str) == 4:
                                int(year_str) # Check if it's a 4-digit number
                            else:
                                year_str = None # Invalid format
                        except (ValueError, TypeError, IndexError):
                             year_str = None # Parsing failed
                        if year_str:
                            value_to_write = [year_str]
                        else:
                             log_message(f"      ⚠️ Warn: Could not extract valid YYYY year from '{processed_value}'. Skipping year tag.")
                             value_to_write = None # Skip writing this tag


                    else: # Default: Treat as text -> list containing [string]
                        text_value = ""
                        try:
                            # Handle common ID3 text frames explicitly if they weren't lists
                            if isinstance(processed_value, (TALB, TPE1, TPE2, TIT2, TCON, TCOM, COMM)):
                                text_value = str(processed_value.text[0]) if processed_value.text else ""
                            else: # General conversion
                                text_value = str(processed_value)
                        except Exception as conversion_err:
                            log_message(f"      ⚠️ Warn: Could not convert value for '{common_key}' to string: {conversion_err}. Skipping tag.")
                            text_value = None # Indicate skipping
                        if text_value is not None:
                             value_to_write = [text_value]

                    # --- Write the Tag to MP4 Object (if value is valid) ---
                    if value_to_write is not None:
                        mp4_file.tags[mp4_key] = value_to_write
                        tags_transferred_count += 1

                except Exception as processing_err:
                    log_message(f"      ❌ Error processing tag '{common_key}' (MP4 key '{mp4_key}') with source value '{source_value_obj}': {processing_err}")
                    log_message(f"         Type: {type(processing_err).__name__}")
                    # Continue to the next tag

        # --- Save the MP4 File (if changes were made) ---
        if tags_transferred_count > 0:
            log_message(f"   💾 Saving {tags_transferred_count} tags to '{os.path.basename(mp4_path)}'...")
            try:
                mp4_file.save()
                log_message(f"   ✅ Successfully transferred metadata.")
                return True
            except Exception as save_err:
                log_message(f"   ❌ Error saving MP4 file '{mp4_path}': {save_err}")
                log_message(f"      Type: {type(save_err).__name__}")
                log_message(f"      Traceback: {traceback.format_exc()}")
                return False
        else:
            log_message(f"   ℹ️ No transferable metadata found or processed in '{os.path.basename(audio_path)}'. MP4 not modified.")
            return False # Indicate nothing was saved

    except mutagen.MutagenError as e:
        log_message(f"   ❌ Mutagen Error during transfer for '{os.path.basename(mp4_path)}': {e}")
        log_message(f"      Type: {type(e).__name__}")
        log_message(f"      Traceback: {traceback.format_exc()}")
        return False
    except Exception as e:
        log_message(f"   ❌ Unexpected Error during transfer function for '{os.path.basename(mp4_path)}': {e}")
        log_message(f"      Type: {type(e).__name__}")
        log_message(f"      Traceback: {traceback.format_exc()}")
        return False

# --- Worker Thread Function ---
def process_files_thread(video_dir, audio_dir, app_instance):
    """The function that runs in the background thread."""
    log_message("🚀 Starting processing thread...")
    processed_count = 0
    success_count = 0
    skipped_count = 0
    match_not_found_count = 0
    error_count = 0
    file_read_error_count = 0 # Add counter for file read errors

    try:
        video_files = [f for f in os.listdir(video_dir) if f.lower().endswith(".mp4") and os.path.isfile(os.path.join(video_dir, f))]
        total_files = len(video_files)
        log_message(f"Found {total_files} MP4 files to process.")

        for index, filename in enumerate(video_files):
            mp4_path = os.path.join(video_dir, filename)
            log_message(f"\n▶️ Processing MP4 ({index+1}/{total_files}): '{filename}'")
            processed_count += 1

            artist, title = parse_mp4_filename(filename)

            if artist and title:
                # find_matching_audio_file now handles internal errors and returns None if match fails or file is unreadable
                audio_match_path = find_matching_audio_file(artist, title, audio_dir)

                if audio_match_path:
                    # Attempt transfer only if a readable match was found
                    if transfer_metadata(audio_match_path, mp4_path):
                        success_count += 1
                    else:
                        # Error occurred during transfer or saving (already logged in transfer_metadata)
                        error_count += 1
                else:
                    # No match found or the potential match was unreadable (already logged in find_matching_audio_file)
                    match_not_found_count +=1 # Increment this counter regardless of the reason for no match path
            else:
                log_message(f"   ⏭️ Skipping - Could not parse artist/title from: '{filename}'")
                skipped_count += 1

        log_message("\n--- Processing Finished ---")
        log_message(f"📊 Summary:")
        log_message(f"   Total MP4s processed:  {processed_count}")
        log_message(f"   Successfully updated:  {success_count} ✅")
        log_message(f"   Audio match not found or unreadable: {match_not_found_count} ❓") # Updated description
        log_message(f"   Skipped (MP4 parse error): {skipped_count} ⏭️")
        log_message(f"   Errors during transfer/save: {error_count} ❌")
        log_message("---------------------------")

    except FileNotFoundError as e:
         log_message(f"\n❌❌ CRITICAL ERROR: Directory not found: {e}. Please check paths. ❌❌")
    except Exception as e:
        log_message(f"\n❌❌ CRITICAL ERROR in processing thread: {e} ❌❌")
        log_message(f"   Type: {type(e).__name__}")
        log_message(f"   Traceback: {traceback.format_exc()}")
    finally:
        log_queue.put("<<PROCESS_COMPLETE>>")


# --- GUI Application Class ---
class MetadataApp:
    def __init__(self, root):
        self.root = root
        self.root.title("MP4 Metadata Transfer Tool 🎬🎶 v1.3") # Version bump
        self.root.minsize(650, 500)

        self.video_dir = tk.StringVar()
        self.audio_dir = tk.StringVar()
        self.processing_thread = None

        main_frame = tk.Frame(root, padx=15, pady=15)
        main_frame.pack(fill=tk.BOTH, expand=True)

        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(2, weight=1)

        tk.Label(main_frame, text="MP4 Video Folder:").grid(row=0, column=0, sticky=tk.W, pady=3)
        video_entry = tk.Entry(main_frame, textvariable=self.video_dir, width=60)
        video_entry.grid(row=0, column=1, sticky=tk.EW, padx=5)
        video_button = tk.Button(main_frame, text="Browse...", command=self.browse_video_dir)
        video_button.grid(row=0, column=2, sticky=tk.E, padx=5)

        tk.Label(main_frame, text="Audio Library Folder:").grid(row=1, column=0, sticky=tk.W, pady=3)
        audio_entry = tk.Entry(main_frame, textvariable=self.audio_dir, width=60)
        audio_entry.grid(row=1, column=1, sticky=tk.EW, padx=5)
        audio_button = tk.Button(main_frame, text="Browse...", command=self.browse_audio_dir)
        audio_button.grid(row=1, column=2, sticky=tk.E, padx=5)

        log_label = tk.Label(main_frame, text="Log Output:")
        log_label.grid(row=2, column=0, sticky=tk.NW, pady=(10, 0))
        self.log_area = scrolledtext.ScrolledText(main_frame, wrap=tk.WORD, height=20, state='disabled', font=("Consolas", 9))
        self.log_area.grid(row=2, column=1, columnspan=2, sticky=tk.NSEW, pady=(5, 0), padx=5)

        button_frame = tk.Frame(main_frame)
        button_frame.grid(row=3, column=0, columnspan=3, pady=15)

        self.start_button = tk.Button(button_frame, text="Start Processing", command=self.start_processing, width=25, height=2, font=("Segoe UI", 10, "bold"))
        self.start_button.pack()

        self.check_log_queue()

    def browse_video_dir(self):
        directory = filedialog.askdirectory(title="Select MP4 Video Folder")
        if directory:
            norm_dir = os.path.normpath(directory)
            self.video_dir.set(norm_dir)
            self.log_to_gui(f"Selected Video Folder: {norm_dir}\n")

    def browse_audio_dir(self):
        directory = filedialog.askdirectory(title="Select Root Audio Library Folder")
        if directory:
            norm_dir = os.path.normpath(directory)
            self.audio_dir.set(norm_dir)
            self.log_to_gui(f"Selected Audio Library: {norm_dir}\n")

    def log_to_gui(self, message):
        self.root.after(0, self._update_log_area, message)

    def _update_log_area(self, message):
        self.log_area.config(state='normal')
        self.log_area.insert(tk.END, message + "\n")
        self.log_area.config(state='disabled')
        self.log_area.see(tk.END)

    def check_log_queue(self):
        try:
            while True:
                message = log_queue.get_nowait()
                if message == "<<PROCESS_COMPLETE>>":
                    self.processing_finished()
                else:
                    self.log_to_gui(message)
        except queue.Empty:
            pass
        finally:
            self.root.after(100, self.check_log_queue)

    def start_processing(self):
        video_path = self.video_dir.get()
        audio_path = self.audio_dir.get()

        if not video_path or not os.path.isdir(video_path):
            messagebox.showerror("Error", f"Video Folder path is invalid or does not exist:\n{video_path}")
            return
        if not audio_path or not os.path.isdir(audio_path):
            messagebox.showerror("Error", f"Audio Library path is invalid or does not exist:\n{audio_path}")
            return

        self.log_area.config(state='normal')
        self.log_area.delete('1.0', tk.END)
        self.log_area.config(state='disabled')

        self.start_button.config(state=tk.DISABLED, text="Processing...")
        self.log_to_gui("--- Starting Metadata Transfer ---")
        self.log_to_gui(f"Video Folder: {video_path}")
        self.log_to_gui(f"Audio Library: {audio_path}")
        self.log_to_gui("----------------------------------")

        self.processing_thread = threading.Thread(
            target=process_files_thread,
            args=(video_path, audio_path, self),
            daemon=True
        )
        self.processing_thread.start()

    def processing_finished(self):
        self.start_button.config(state=tk.NORMAL, text="Start Processing")
        messagebox.showinfo("Complete", "Metadata processing finished. Please check the log output for details and any errors.")

# --- Main Execution ---
if __name__ == "__main__":
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except ImportError: pass
    except AttributeError:
         try: windll.user32.SetProcessDPIAware()
         except: pass

    root = tk.Tk()
    app = MetadataApp(root)
    root.mainloop()
