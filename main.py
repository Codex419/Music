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
        self.search_type_var = tk.StringVar(value="Song")
        search_types = ["Song", "Artist", "Album", "Url"]
        ttk.OptionMenu(control_frame, self.search_type_var, search_types[0], *search_types).pack(side=tk.LEFT, padx=2)

        self.search_var = tk.StringVar()
        entry = ttk.Entry(control_frame, textvariable=self.search_var, width=40)
        entry.pack(side=tk.LEFT, padx=5)
        entry.bind("<Return>", lambda e: self.add_to_queue())

        ttk.Button(control_frame, text="Add", command=self.add_to_queue).pack(side=tk.LEFT, padx=2)

        # Import Menu
        import_btn = ttk.Menubutton(control_frame, text="Import")
        import_menu = tk.Menu(import_btn, tearoff=0)
        import_menu.add_command(label="Spotify/YouTube URL", command=self.import_url)
        import_menu.add_command(label="YouTube Cookies (Instructions)", command=self.show_cookies_help)
        import_btn.configure(menu=import_menu)
        import_btn.pack(side=tk.LEFT, padx=2)

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
        # Helper to create label+entry/combobox
        def add_setting(parent, label, key_path, options=None):
            frame = ttk.Frame(parent)
            frame.pack(fill=tk.X, pady=2)
            ttk.Label(frame, text=label, width=20).pack(side=tk.LEFT)

            val = self.get_config_value(key_path)
            var = tk.StringVar(value=str(val))

            if options:
                widget = ttk.Combobox(frame, textvariable=var, values=options, state="readonly")
            else:
                widget = ttk.Entry(frame, textvariable=var)

            widget.pack(side=tk.LEFT, fill=tk.X, expand=True)

            # Trace change to update config
            def on_change(*args):
                self.set_config_value(key_path, var.get())
                if key_path == ['ui', 'theme']:
                    self.apply_theme(var.get())

            var.trace_add('write', on_change)

        # Paths
        lf_paths = ttk.LabelFrame(self.tab_settings, text="Paths")
        lf_paths.pack(fill=tk.X, padx=5, pady=5)
        add_setting(lf_paths, "Music Dir", ['paths', 'music_dir'])
        add_setting(lf_paths, "Video Dir", ['paths', 'video_dir'])

        # Tidal
        lf_tidal = ttk.LabelFrame(self.tab_settings, text="Tidal")
        lf_tidal.pack(fill=tk.X, padx=5, pady=5)
        add_setting(lf_tidal, "Token", ['tidal', 'token'])
        add_setting(lf_tidal, "Client ID", ['tidal', 'client_id'])
        add_setting(lf_tidal, "Client Secret", ['tidal', 'client_secret'])
        add_setting(lf_tidal, "Quality", ['tidal', 'quality'], ["LOW", "HIGH", "LOSSLESS", "HI_RES"])

        # Deezer
        lf_deezer = ttk.LabelFrame(self.tab_settings, text="Deezer")
        lf_deezer.pack(fill=tk.X, padx=5, pady=5)
        add_setting(lf_deezer, "ARL", ['deezer', 'arl'])
        add_setting(lf_deezer, "Quality", ['deezer', 'quality'], ["MP3_128", "MP3_320", "FLAC"])

        # YouTube
        lf_youtube = ttk.LabelFrame(self.tab_settings, text="YouTube")
        lf_youtube.pack(fill=tk.X, padx=5, pady=5)
        add_setting(lf_youtube, "Cookies Path", ['youtube', 'cookies_path'])

        # AI
        lf_ai = ttk.LabelFrame(self.tab_settings, text="AI")
        lf_ai.pack(fill=tk.X, padx=5, pady=5)
        add_setting(lf_ai, "Model Size", ['ai', 'model_size'], ["tiny", "base", "small", "medium", "large-v2"])
        add_setting(lf_ai, "Precision", ['ai', 'precision'], ["float16", "int8_float16", "int8"])
        add_setting(lf_ai, "Device", ['ai', 'device'], ["cpu", "cuda", "auto"])
        add_setting(lf_ai, "Beam Size", ['ai', 'beam_size'])

        # Formats
        lf_fmt = ttk.LabelFrame(self.tab_settings, text="Formats")
        lf_fmt.pack(fill=tk.X, padx=5, pady=5)
        add_setting(lf_fmt, "Audio Format", ['formats', 'audio_format'], ["flac", "mp3", "aac", "wav"])
        add_setting(lf_fmt, "Video Format", ['formats', 'video_format'], ["mp4", "mkv", "webm"])
        add_setting(lf_fmt, "Video Res", ['formats', 'video_resolution'], ["2160p", "1440p", "1080p", "720p", "480p"])

        # UI
        lf_ui = ttk.LabelFrame(self.tab_settings, text="UI")
        lf_ui.pack(fill=tk.X, padx=5, pady=5)
        add_setting(lf_ui, "Theme", ['ui', 'theme'], ["Dark", "Light"])
        add_setting(lf_ui, "Search Results", ['ui', 'search_results'])

    def apply_theme(self, theme_name):
        style = ttk.Style()
        if theme_name == "Dark":
            bg_color = "#2E2E2E"
            fg_color = "#FFFFFF"
            field_bg = "#404040"
            style.theme_use('clam')
            style.configure(".", background=bg_color, foreground=fg_color, fieldbackground=field_bg)
            style.configure("TLabel", background=bg_color, foreground=fg_color)
            style.configure("TButton", background="#333333", foreground=fg_color, bordercolor="#555555")
            style.configure("TEntry", fieldbackground=field_bg, foreground=fg_color)
            style.configure("Treeview", background=field_bg, foreground=fg_color, fieldbackground=field_bg)
            style.map("Treeview", background=[('selected', '#007ACC')], foreground=[('selected', 'white')])
            self.configure(background=bg_color)
        else:
            style.theme_use('clam') # Reset to standard/light-ish
            # Explicitly reset colors if needed, or just let 'clam' default handle it
            style.configure(".", background="#F0F0F0", foreground="black", fieldbackground="white")
            self.configure(background="#F0F0F0")

        # Save & Repair
        btn_frame = ttk.Frame(self.tab_settings)
        btn_frame.pack(pady=10)
        ttk.Button(btn_frame, text="Save Configuration", command=self.save_config).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Repair Config", command=self.repair_config).pack(side=tk.LEFT, padx=5)

    def repair_config(self):
        # Restore defaults
        default_config = {
            "paths": {"music_dir": "Output/Music", "video_dir": "Output/Music Videos", "staging_dir": "Output/Staging"},
            "tidal": {"token": "", "client_id": "", "client_secret": "", "quality": "HI_RES"},
            "deezer": {"arl": "", "quality": "FLAC"},
            "youtube": {"cookies_path": "", "token": ""},
            "web_dl": {"audio_format": "flac", "video_format": "mp4", "download_delay": 2},
            "ai": {"model_size": "medium", "precision": "int8", "device": "auto", "vad_filter": True, "beam_size": 5},
            "ui": {"theme": "Dark", "search_results": 5, "fallback_enabled": True},
            "formats": {"audio_format": "flac", "video_format": "mp4", "video_resolution": "1080p", "lyric_format": "lrc", "subtitle_format": "srt"}
        }
        self.config = default_config
        self.save_config()
        messagebox.showinfo("Config Repair", "Configuration restored to defaults.")

    def setup_help_tab(self):
        # Create a canvas with scrollbar for help text
        canvas = tk.Canvas(self.tab_help)
        scrollbar = ttk.Scrollbar(self.tab_help, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        text = """
        Music Downloader Help
        =====================

        1. Configuration & Tokens
        -------------------------
        The application works with EITHER Tidal OR Deezer. You do not need both.

        [Tidal]
        - To get a token, you typically need to sniff traffic or use a script.
        - Common method: Use 'Tidal-Media-Downloader' auth script or inspect web headers.
        - Enter token in Settings > Tidal.

        [Deezer]
        - Log in to Deezer in your browser.
        - Open Developer Tools (F12) > Application > Cookies.
        - Find the 'arl' cookie. Copy its value.
        - Enter it in Settings > Deezer > ARL.

        [YouTube]
        - Required for Music Video downloads.
        - To avoid rate limits/age restrictions, use cookies.
        - Install 'Get cookies.txt LOCALLY' extension.
        - Download cookies.txt from YouTube while logged in.
        - Place in app folder or point to it in Settings.

        2. Usage
        --------
        - Queue Tab:
          - Select Search Type (Song, Artist, Album, Url).
          - Type query or paste URL.
          - Click 'Add'.
        - Import Menu:
          - 'Spotify/YouTube URL': Paste links to playlists/albums.
        - Interactive Mode:
          - Check this to manually approve/modify matches before downloading.

        3. Pipeline
        -----------
        1. Search Audio: Tidal -> Deezer -> MusicBrainz (Fallback).
        2. Download Audio: Best available quality (FLAC/Hi-Res).
        3. Transcribe: AI generates .lrc lyrics.
        4. Search Video: YouTube (Official Music Video).
        5. Sync: Copy tags/art from Audio to Video.
        6. Transcribe Video: AI generates .srt subtitles.
        7. Archive: Move to Output folder sorted by Artist/Album.
        """
        lbl = ttk.Label(scrollable_frame, text=text, justify=tk.LEFT, font=("Consolas", 10))
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

        search_type = self.search_type_var.get()

        # Override type if URL detected
        if "http" in query:
            search_type = "Url"

        if search_type == "Url":
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
            elif "youtube.com" in query or "youtu.be" in query:
                 # Assume YouTube import (Music Video or Playlist)
                 # For simplicity, treat as song
                 self.tree.insert("", tk.END, values=(query, "YouTube", "?", "Queued"))
                 logger.info(f"Added YouTube URL: {query}")

        elif search_type == "Artist":
            tracks = self.ingest.expand_artist(query)
            for t in tracks:
                parts = t.split(" - ")
                artist = parts[0].strip() if len(parts) > 1 else "?"
                song = parts[1].strip() if len(parts) > 1 else t
                self.tree.insert("", tk.END, values=(song, artist, "?", "Queued"))
            logger.info(f"Expanded {len(tracks)} tracks for Artist: {query}")

        elif search_type == "Album":
            tracks = self.ingest.expand_album(query)
            for t in tracks:
                 parts = t.split(" - ")
                 artist = parts[0].strip() if len(parts) > 1 else "?"
                 song = parts[1].strip() if len(parts) > 1 else t
                 self.tree.insert("", tk.END, values=(song, artist, "?", "Queued"))
            logger.info(f"Expanded {len(tracks)} tracks for Album: {query}")

        else: # Song
            # Simple text entry
            parts = query.split("-")
            artist = parts[0].strip() if len(parts) > 1 else "?"
            song = parts[1].strip() if len(parts) > 1 else query
            self.tree.insert("", tk.END, values=(song, artist, "?", "Queued"))
            logger.info(f"Added to queue: {query}")

        self.search_var.set("")

    def show_cookies_help(self):
        msg = ("To import YouTube Cookies:\n\n"
               "1. Install 'Get cookies.txt LOCALLY' extension for Chrome/Firefox.\n"
               "2. Go to YouTube, log in.\n"
               "3. Click extension to download 'cookies.txt'.\n"
               "4. Place 'cookies.txt' in the application folder.\n"
               "5. Go to Settings > YouTube and verify the path.")
        messagebox.showinfo("YouTube Cookies Instructions", msg)

    def import_url(self):
        url = filedialog.askstring("Import", "Enter Spotify URL or Playlist:")
        if url:
            self.add_to_queue(url)

    def ask_user_approval(self, query, track_info, thumbnail_url=None):
        """Show popup in main thread and wait for result."""
        self.user_decision = None
        self.user_input_event.clear()

        def show_dialog():
            # Create custom dialog
            dialog = tk.Toplevel(self)
            dialog.title("Approval Required")
            dialog.geometry("500x400") # Increased size for details

            # Details Frame
            info_frame = ttk.Frame(dialog)
            info_frame.pack(pady=10, fill=tk.BOTH, expand=True)

            ttk.Label(info_frame, text=f"Query: {query}", font=("Segoe UI", 10, "bold")).pack(pady=2)
            ttk.Label(info_frame, text=f"Match Found:", font=("Segoe UI", 9)).pack(pady=(5,0))

            # Display multiline info
            details_text = tk.Text(info_frame, height=8, width=50, relief=tk.FLAT, background="#f0f0f0")
            details_text.insert(tk.END, track_info)
            details_text.config(state=tk.DISABLED)
            details_text.pack(pady=5, padx=10)

            # Thumbnail (Placeholder logic - requires async fetch in non-GUI thread usually)
            # For simplicity, we just show a label if URL exists
            if thumbnail_url:
                ttk.Label(info_frame, text=f"[Thumbnail URL: {thumbnail_url}]").pack(pady=5)

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
                    self.user_decision = "skip"
                self.user_input_event.set()
                dialog.destroy()

            ttk.Button(btn_frame, text="Approve", command=approve).pack(side=tk.LEFT, padx=5)
            ttk.Button(btn_frame, text="Modify", command=modify).pack(side=tk.LEFT, padx=5)
            ttk.Button(btn_frame, text="Skip", command=skip).pack(side=tk.LEFT, padx=5)

            dialog.transient(self)
            dialog.grab_set()
            self.wait_window(dialog)

        self.after(0, show_dialog)
        self.user_input_event.wait()
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
                    # Format detailed info
                    if track:
                        details = (f"Source: {source}\n"
                                   f"Title: {track.name if hasattr(track, 'name') else track.title}\n"
                                   f"Artist: {track.artist.name if hasattr(track, 'artist') else 'Unknown'}\n"
                                   f"Album: {track.album.name if hasattr(track, 'album') else 'Unknown'}")
                    else:
                        details = "No match found."

                    decision = self.ask_user_approval(query, details)

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
