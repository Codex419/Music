import tkinter as tk
from tkinter import ttk, messagebox, filedialog, scrolledtext
import threading
import queue
import logging
import yaml
import time
from pathlib import Path

# Import Modules
from modules.ingest import Ingest
from modules.enrichment import Enrichment
from modules.governance import Governance

# Try importing DnD
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    TK_ROOT = TkinterDnD.Tk
    DND_AVAILABLE = True
except ImportError:
    TK_ROOT = tk.Tk
    DND_AVAILABLE = False
    print("Warning: tkinterdnd2 not found. Drag-and-drop disabled.")

# Logging Setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger()

class TextHandler(logging.Handler):
    def __init__(self, text_widget):
        logging.Handler.__init__(self)
        self.text_widget = text_widget
        self.queue = queue.Queue()

    def emit(self, record):
        msg = self.format(record)
        self.queue.put(msg)

    def poll(self):
        while not self.queue.empty():
            msg = self.queue.get()
            self.text_widget.configure(state='normal')
            self.text_widget.insert(tk.END, msg + '\n')
            self.text_widget.configure(state='disabled')
            self.text_widget.yview(tk.END)
        self.text_widget.after(100, self.poll)

class MusicDownloaderApp(TK_ROOT):
    def __init__(self):
        super().__init__()
        self.title("Music Downloader - Production Pipeline")
        self.geometry("1000x700")

        # Load Config
        self.config_path = "config.yaml"
        self.config = self.load_config()

        # Initialize Modules
        self.ingest = Ingest(self.config)
        self.enrichment = Enrichment(self.config)
        self.governance = Governance(self.config)

        # Job Queue
        self.job_queue = queue.Queue()
        self.processing = False
        self.stop_event = threading.Event()

        # Interactive Mode State
        self.interactive_mode = tk.BooleanVar(value=False)
        self.user_decision = None
        self.user_input_event = threading.Event()

        # UI Setup
        self.create_widgets()

        # Start Worker Thread Logic (on demand)

    def load_config(self):
        try:
            with open(self.config_path, 'r') as f:
                return yaml.safe_load(f)
        except Exception as e:
            messagebox.showerror("Config Error", f"Could not load config.yaml: {e}")
            return {}

    def save_config(self):
        try:
            with open(self.config_path, 'w') as f:
                yaml.dump(self.config, f)
            messagebox.showinfo("Settings", "Configuration saved.")
        except Exception as e:
            messagebox.showerror("Config Error", f"Could not save config.yaml: {e}")

    def create_widgets(self):
        # Notebook (Tabs)
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Tab 1: Queue
        self.tab_queue = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_queue, text="Job Queue")
        self.setup_queue_tab()

        # Tab 2: Settings
        self.tab_settings = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_settings, text="Settings")
        self.setup_settings_tab()

        # Tab 3: Help
        self.tab_help = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_help, text="Help")
        self.setup_help_tab()

        # Console
        self.console_frame = ttk.LabelFrame(self, text="Console Log")
        self.console_frame.pack(fill=tk.BOTH, expand=False, padx=5, pady=5, side=tk.BOTTOM)
        self.console_text = scrolledtext.ScrolledText(self.console_frame, height=8, state='disabled')
        self.console_text.pack(fill=tk.BOTH, expand=True)

        # Logging Handler
        self.log_handler = TextHandler(self.console_text)
        logger.addHandler(self.log_handler)
        self.console_text.after(100, self.log_handler.poll)

    def setup_queue_tab(self):
        # Controls
        control_frame = ttk.Frame(self.tab_queue)
        control_frame.pack(fill=tk.X, padx=5, pady=5)

        ttk.Label(control_frame, text="Search/Add:").pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        entry = ttk.Entry(control_frame, textvariable=self.search_var, width=40)
        entry.pack(side=tk.LEFT, padx=5)
        entry.bind("<Return>", lambda e: self.add_to_queue())

        ttk.Button(control_frame, text="Add", command=self.add_to_queue).pack(side=tk.LEFT, padx=2)
        ttk.Button(control_frame, text="Import URL", command=self.import_url).pack(side=tk.LEFT, padx=2)

        # Interactive Mode Checkbox
        ttk.Checkbutton(control_frame, text="Interactive Mode", variable=self.interactive_mode).pack(side=tk.LEFT, padx=10)

        self.btn_start = ttk.Button(control_frame, text="Start Processing", command=self.start_processing)
        self.btn_start.pack(side=tk.RIGHT, padx=5)
        self.btn_stop = ttk.Button(control_frame, text="Stop", command=self.stop_processing, state=tk.DISABLED)
        self.btn_stop.pack(side=tk.RIGHT)

        # Treeview
        columns = ("Song", "Artist", "Album", "Status")
        self.tree = ttk.Treeview(self.tab_queue, columns=columns, show='headings')
        for col in columns:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=150)
        self.tree.column("Status", width=300)
        self.tree.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Drag Drop
        if DND_AVAILABLE:
            self.tree.drop_target_register(DND_FILES)
            self.tree.dnd_bind('<<Drop>>', self.handle_drop)

    def setup_settings_tab(self):
        # Helper to create label+entry
        def add_setting(parent, label, key_path):
            frame = ttk.Frame(parent)
            frame.pack(fill=tk.X, pady=2)
            ttk.Label(frame, text=label, width=20).pack(side=tk.LEFT)
            var = tk.StringVar(value=str(self.get_config_value(key_path)))
            entry = ttk.Entry(frame, textvariable=var)
            entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
            # Trace change to update config
            var.trace_add('write', lambda *args: self.set_config_value(key_path, var.get()))

        # Paths
        lf_paths = ttk.LabelFrame(self.tab_settings, text="Paths")
        lf_paths.pack(fill=tk.X, padx=5, pady=5)
        add_setting(lf_paths, "Music Dir", ['paths', 'music_dir'])
        add_setting(lf_paths, "Video Dir", ['paths', 'video_dir'])

        # Tidal
        lf_tidal = ttk.LabelFrame(self.tab_settings, text="Tidal")
        lf_tidal.pack(fill=tk.X, padx=5, pady=5)
        add_setting(lf_tidal, "Token", ['tidal', 'token'])
        add_setting(lf_tidal, "Quality", ['tidal', 'quality'])

        # Deezer
        lf_deezer = ttk.LabelFrame(self.tab_settings, text="Deezer")
        lf_deezer.pack(fill=tk.X, padx=5, pady=5)
        add_setting(lf_deezer, "ARL", ['deezer', 'arl'])

        # Save Button
        ttk.Button(self.tab_settings, text="Save Configuration", command=self.save_config).pack(pady=10)

    def setup_help_tab(self):
        text = """
        Music Downloader Help

        1. Tokens: Get your Tidal/Deezer tokens and enter them in Settings.
        2. Queue: Type 'Artist - Song' or paste a Spotify URL to add to queue.
        3. Processing: Click 'Start Processing' to begin the pipeline.

        Pipeline:
        - Search Tidal (Priority) -> Deezer (Fallback) for Audio (FLAC).
        - Transcribe Audio to LRC.
        - Search YouTube for Music Video.
        - Sync Metadata from Audio to Video.
        - Transcribe Video to SRT.
        - Archive to structured folders.
        """
        lbl = ttk.Label(self.tab_help, text=text, justify=tk.LEFT, font=("Consolas", 10))
        lbl.pack(padx=10, pady=10, anchor=tk.NW)

    def get_config_value(self, keys):
        val = self.config
        for k in keys:
            val = val.get(k, {})
        return val if not isinstance(val, dict) else ""

    def set_config_value(self, keys, value):
        d = self.config
        for k in keys[:-1]:
            d = d.setdefault(k, {})
        d[keys[-1]] = value

    def add_to_queue(self, item=None):
        query = item or self.search_var.get()
        if not query: return

        # Identify if URL or Text
        if "spotify.com" in query:
            if "playlist" in query or "album" in query:
                # Expand Playlist/Album
                tracks = self.ingest.parse_spotify_playlist(query)
                for t in tracks:
                    parts = t.split(" - ")
                    artist = parts[0].strip() if len(parts) > 1 else "?"
                    song = parts[1].strip() if len(parts) > 1 else t
                    self.tree.insert("", tk.END, values=(song, artist, "?", "Queued"))
                logger.info(f"Expanded {len(tracks)} tracks from Spotify URL")
            else:
                meta = self.ingest.parse_spotify_url(query)
                if meta:
                    display = f"{meta['artist']} - {meta['title']}"
                    self.tree.insert("", tk.END, values=(meta['title'], meta['artist'], "?", "Queued"))
                    logger.info(f"Added from URL: {display}")
                else:
                    logger.error("Failed to parse Spotify URL")
            self.search_var.set("")

        elif query.lower().startswith("artist:"):
            # Expand Artist
            artist_name = query[7:].strip()
            tracks = self.ingest.expand_artist(artist_name)
            for t in tracks:
                parts = t.split(" - ")
                artist = parts[0].strip() if len(parts) > 1 else "?"
                song = parts[1].strip() if len(parts) > 1 else t
                self.tree.insert("", tk.END, values=(song, artist, "?", "Queued"))
            logger.info(f"Expanded {len(tracks)} tracks for Artist: {artist_name}")
            self.search_var.set("")

        elif query.lower().startswith("album:"):
            # Expand Album
            album_name = query[6:].strip()
            tracks = self.ingest.expand_album(album_name)
            for t in tracks:
                 parts = t.split(" - ")
                 artist = parts[0].strip() if len(parts) > 1 else "?"
                 song = parts[1].strip() if len(parts) > 1 else t
                 self.tree.insert("", tk.END, values=(song, artist, "?", "Queued"))
            logger.info(f"Expanded {len(tracks)} tracks for Album: {album_name}")
            self.search_var.set("")

        else:
            # Simple text entry
            parts = query.split("-")
            artist = parts[0].strip() if len(parts) > 1 else "?"
            song = parts[1].strip() if len(parts) > 1 else query
            self.tree.insert("", tk.END, values=(song, artist, "?", "Queued"))
            self.search_var.set("")
            logger.info(f"Added to queue: {query}")

    def import_url(self):
        url = filedialog.askstring("Import", "Enter Spotify URL or Playlist:")
        if url:
            self.add_to_queue(url)

    def ask_user_approval(self, query, track_info):
        """Show popup in main thread and wait for result."""
        self.user_decision = None
        self.user_input_event.clear()

        def show_dialog():
            # Create custom dialog
            dialog = tk.Toplevel(self)
            dialog.title("Approval Required")
            dialog.geometry("400x200")

            ttk.Label(dialog, text=f"Query: {query}").pack(pady=5)
            ttk.Label(dialog, text=f"Found: {track_info}").pack(pady=5)

            btn_frame = ttk.Frame(dialog)
            btn_frame.pack(pady=10)

            def approve():
                self.user_decision = "approve"
                self.user_input_event.set()
                dialog.destroy()

            def skip():
                self.user_decision = "skip"
                self.user_input_event.set()
                dialog.destroy()

            def modify():
                new_query = filedialog.askstring("Modify Search", "Enter new query:", parent=dialog)
                if new_query:
                    self.user_decision = f"modify:{new_query}"
                else:
                    self.user_decision = "skip" # Cancel acts as skip
                self.user_input_event.set()
                dialog.destroy()

            ttk.Button(btn_frame, text="Approve", command=approve).pack(side=tk.LEFT, padx=5)
            ttk.Button(btn_frame, text="Modify", command=modify).pack(side=tk.LEFT, padx=5)
            ttk.Button(btn_frame, text="Skip", command=skip).pack(side=tk.LEFT, padx=5)

            dialog.transient(self)
            dialog.grab_set()
            self.wait_window(dialog)

        self.after(0, show_dialog)
        self.user_input_event.wait() # Block worker thread
        return self.user_decision

    def handle_drop(self, event):
        data = event.data
        if data:
            # Handle file paths or text drops
            # For simplicity, treat as text query if not file
            self.add_to_queue(data)

    def start_processing(self):
        if self.processing: return
        self.processing = True
        self.stop_event.clear()
        self.btn_start.config(state=tk.DISABLED)
        self.btn_stop.config(state=tk.NORMAL)

        # Build Queue from Treeview
        items = self.tree.get_children()
        for i in items:
            vals = self.tree.item(i)['values']
            status = vals[3]
            if status == "Queued":
                self.job_queue.put(i)

        threading.Thread(target=self.process_queue, daemon=True).start()

    def stop_processing(self):
        self.stop_event.set()
        self.processing = False
        self.btn_start.config(state=tk.NORMAL)
        self.btn_stop.config(state=tk.DISABLED)
        logger.info("Stopping processing...")

    def update_status(self, item_id, status):
        self.after(0, lambda: self._safe_update_status(item_id, status))

    def _safe_update_status(self, item_id, status):
        try:
            vals = self.tree.item(item_id)['values']
            self.tree.item(item_id, values=(vals[0], vals[1], vals[2], status))
        except Exception:
            pass

    def process_queue(self):
        while not self.stop_event.is_set() and not self.job_queue.empty():
            item_id = self.job_queue.get()
            vals = self.tree.item(item_id)['values']
            song, artist = vals[0], vals[1]
            query = f"{artist} - {song}" if artist != "?" else song

            logger.info(f"Processing: {query}")
            self.update_status(item_id, "Searching Audio...")

            try:
                # 1. Audio Search
                track = self.ingest.search_tidal(query)
                source = "Tidal"
                if not track:
                    track = self.ingest.search_deezer(query)
                    source = "Deezer"

                # MusicBrainz Fallback
                if not track:
                    logger.info("Tidal/Deezer search failed. Trying MusicBrainz fallback...")
                    mb_meta = self.ingest.get_musicbrainz_metadata(query)
                    if mb_meta:
                        refined_query = f"{mb_meta['artist']} - {mb_meta['title']}"
                        logger.info(f"MusicBrainz found metadata: {refined_query}. Retrying search...")
                        track = self.ingest.search_tidal(refined_query)
                        source = "Tidal"
                        if not track:
                            track = self.ingest.search_deezer(refined_query)
                            source = "Deezer"

                # Interactive Approval
                if self.interactive_mode.get():
                    track_info = f"{source}: {track.name if track else 'Not Found'}"
                    decision = self.ask_user_approval(query, track_info)

                    if decision == "skip":
                        self.update_status(item_id, "Skipped by User")
                        continue
                    elif decision and decision.startswith("modify:"):
                        query = decision.split(":", 1)[1]
                        logger.info(f"Query modified to: {query}")
                        # Retry search with new query
                        track = self.ingest.search_tidal(query)
                        if not track:
                            track = self.ingest.search_deezer(query)
                            source = "Deezer"

                # Download
                audio_path = None
                if track:
                    self.update_status(item_id, f"Downloading {source}...")
                    if source == "Tidal":
                        audio_path = self.ingest.download_tidal(track, f"temp_{int(time.time())}.flac")
                    else:
                        audio_path = self.ingest.download_deezer(track, f"temp_{int(time.time())}.flac")

                if not audio_path:
                    logger.warning(f"Audio not found or download failed for {query}")
                    self.update_status(item_id, "Audio Download Failed - Skipping")
                    continue

                # Get Metadata
                metadata = {'artist': artist, 'title': song, 'album': 'Unknown', 'date': '2023'}
                if track:
                    # Attempt to extract metadata from track object if available
                    try:
                        if hasattr(track, 'artist'): metadata['artist'] = track.artist.name
                        if hasattr(track, 'album'): metadata['album'] = track.album.name
                        if hasattr(track, 'title'): metadata['title'] = track.title
                    except Exception as meta_e:
                        logger.warning(f"Error extracting metadata from track object: {meta_e}")

                # 2. Audio Enrichment
                self.update_status(item_id, "Transcribing Audio...")
                lrc_path = self.enrichment.transcribe_file(audio_path, 'lrc')
                if lrc_path:
                    self.enrichment.embed_lyrics(audio_path, lrc_path)

                # 3. Video Acquisition
                self.update_status(item_id, "Acquiring Video...")
                video_info = self.ingest.search_youtube_video(query)
                video_path = None
                if video_info:
                    video_path = self.ingest.download_youtube_video(video_info, f"temp_vid_{int(time.time())}.mp4")

                if video_path:
                    # 4. Video Enrichment
                    self.update_status(item_id, "Syncing Metadata...")
                    self.enrichment.sync_metadata(audio_path, video_path)

                    self.update_status(item_id, "Transcribing Video...")
                    self.enrichment.transcribe_file(video_path, 'srt')

                    # 5. Archive Video
                    self.governance.archive_video(video_path, metadata)

                # 6. Archive Audio
                self.governance.archive_audio(audio_path, metadata)

                self.update_status(item_id, "Completed")
                logger.info(f"Completed: {query}")

            except Exception as e:
                logger.error(f"Error processing {query}: {e}")
                self.update_status(item_id, "Error")
                import traceback
                logger.error(traceback.format_exc())

        self.processing = False
        self.btn_start.config(state=tk.NORMAL)
        self.btn_stop.config(state=tk.DISABLED)
        logger.info("Queue finished.")

if __name__ == "__main__":
    app = MusicDownloaderApp()
    app.mainloop()
