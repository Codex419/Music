import tkinter as tk
from tkinter import ttk, messagebox, filedialog, scrolledtext
import threading
import queue
import logging
import yaml
import time
import argparse
import sys
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
        ttk.Button(lf_tidal, text="Login to Tidal", command=self.tidal_login_flow).pack(pady=5)

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
        add_setting(lf_ai, "Model Size", ['ai', 'model_size'], ["tiny", "base", "small", "medium", "large-v2", "turbo"])
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

    def tidal_login_flow(self):
        """Initiate Tidal Device Authorization Flow."""
        try:
            import tidalapi
            session = tidalapi.Session()

            # Use get_link_login to get the code/url without blocking or printing
            try:
                login = session.get_link_login()
            except Exception as e:
                logger.error(f"Error getting Tidal login link: {e}")
                messagebox.showerror("Login Error", f"Failed to start login flow: {e}")
                return

            url = getattr(login, 'verification_uri_complete', None) or getattr(login, 'verification_uri', 'https://link.tidal.com')
            code = getattr(login, 'user_code', 'Unknown')

            # Show Popup in Main Thread
            self.show_tidal_popup(url, code)

            # Create a dedicated thread to wait for login
            def login_wait_thread():
                try:
                    # process_link_login blocks until user logs in or timeout
                    session.process_link_login(login)
                    if session.check_login():
                        # Login Successful
                        self.after(0, lambda: self.on_tidal_login_success(session))
                    else:
                        logger.error("Tidal login check failed after process_link_login")
                        self.after(0, lambda: messagebox.showerror("Login Failed", "Login not verified."))
                except Exception as e:
                    logger.error(f"Tidal login wait error: {e}")
                    self.after(0, lambda: messagebox.showerror("Login Error", f"Wait process failed: {e}"))

            threading.Thread(target=login_wait_thread, daemon=True).start()

        except Exception as e:
            messagebox.showerror("Error", f"Failed to init Tidal login: {e}")

    def show_tidal_popup(self, url, code):
        """Show dialog with copyable link and code."""
        import webbrowser
        dialog = tk.Toplevel(self)
        dialog.title("Tidal Authorization")
        dialog.geometry("400x250")

        ttk.Label(dialog, text="1. Copy this code:", font=("Segoe UI", 10)).pack(pady=5)

        code_entry = ttk.Entry(dialog, font=("Consolas", 12, "bold"), justify='center')
        code_entry.insert(0, code)
        code_entry.config(state='readonly')
        code_entry.pack(pady=5)

        ttk.Label(dialog, text="2. Click 'Open Link' and enter the code:", font=("Segoe UI", 10)).pack(pady=5)

        link_btn = ttk.Button(dialog, text="Open Link", command=lambda: webbrowser.open(url))
        link_btn.pack(pady=5)

        ttk.Label(dialog, text="3. Wait here after authorizing...", font=("Segoe UI", 9, "italic")).pack(pady=10)

    def on_tidal_login_success(self, session):
        """Save credentials on success."""
        messagebox.showinfo("Success", "Tidal Login Successful!")
        # Update Config
        self.set_config_value(['tidal', 'token_type'], session.token_type)
        self.set_config_value(['tidal', 'access_token'], session.access_token)
        self.set_config_value(['tidal', 'refresh_token'], session.refresh_token)
        self.set_config_value(['tidal', 'expiry_time'], session.expiry_time.timestamp() if session.expiry_time else 0)
        self.save_config()
        logger.info("Tidal credentials saved.")

    def repair_config(self):
        # Restore defaults
        default_config = {
            "paths": {"music_dir": "Output/Music", "video_dir": "Output/Music Videos", "staging_dir": "Output/Staging"},
            "tidal": {"token": "", "client_id": "", "client_secret": "", "quality": "HI_RES", "access_token": "", "refresh_token": "", "token_type": "", "expiry_time": 0},
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

    def ask_user_selection(self, query, candidates, search_type="Audio"):
        """Show selection popup with list of candidates."""
        self.user_decision = None
        self.user_input_event.clear()

        def show_dialog():
            dialog = tk.Toplevel(self)
            dialog.title(f"Select {search_type}: {query}")
            dialog.geometry("800x600")

            # Configure Grid weights
            dialog.columnconfigure(0, weight=1)
            dialog.rowconfigure(1, weight=1)

            # Header
            ttk.Label(dialog, text=f"Search Results for '{query}'", font=("Segoe UI", 12, "bold")).grid(row=0, column=0, pady=10)

            # Canvas for Scrollable List
            canvas = tk.Canvas(dialog)
            scrollbar = ttk.Scrollbar(dialog, orient="vertical", command=canvas.yview)
            scroll_frame = ttk.Frame(canvas)

            scroll_frame.bind(
                "<Configure>",
                lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
            )

            canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
            canvas.configure(yscrollcommand=scrollbar.set)

            canvas.grid(row=1, column=0, sticky="nsew", padx=10)
            scrollbar.grid(row=1, column=1, sticky="ns")

            # Populate Candidates
            if not candidates:
                ttk.Label(scroll_frame, text="No results found.").pack(pady=20)
            else:
                for idx, cand in enumerate(candidates):
                    # Item Frame
                    frame = ttk.Frame(scroll_frame, relief="groove", borderwidth=1)
                    frame.pack(fill="x", pady=5, padx=5, expand=True)

                    # Info
                    info_text = f"{cand['title']}\n{cand['artist']} - {cand['album']}\nSource: {cand['source']} | Duration: {cand['duration']}s"

                    # Image Placeholder (Async loading too complex for this snippet, showing text)
                    if cand.get('cover_url'):
                        ttk.Label(frame, text="[IMG]", width=6).pack(side="left", padx=5) # Placeholder

                    lbl = ttk.Label(frame, text=info_text, justify="left", font=("Segoe UI", 9))
                    lbl.pack(side="left", padx=10, fill="x", expand=True)

                    # Select Button
                    btn = ttk.Button(frame, text="Select", command=lambda c=cand: select_candidate(c))
                    btn.pack(side="right", padx=10)

            # Footer Actions
            btn_frame = ttk.Frame(dialog)
            btn_frame.grid(row=2, column=0, pady=10)

            def select_candidate(cand):
                self.user_decision = cand
                self.user_input_event.set()
                dialog.destroy()

            def modify_search():
                new_q = filedialog.askstring("Modify Search", "Enter new query:", parent=dialog)
                if new_q:
                    self.user_decision = f"modify:{new_q}"
                    self.user_input_event.set()
                    dialog.destroy()

            def skip():
                self.user_decision = "skip"
                self.user_input_event.set()
                dialog.destroy()

            ttk.Button(btn_frame, text="Modify Search", command=modify_search).pack(side=tk.LEFT, padx=5)
            ttk.Button(btn_frame, text="Skip Item", command=skip).pack(side=tk.LEFT, padx=5)

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
        limit = self.config.get('web_dl', {}).get('concurrent_limit', 3)
        self.download_semaphore = threading.Semaphore(limit)

        while not self.stop_event.is_set() and not self.job_queue.empty():
            item_id = self.job_queue.get()
            vals = self.tree.item(item_id)['values']
            song, artist = vals[0], vals[1]
            query = f"{artist} - {song}" if artist != "?" else song

            logger.info(f"Processing: {query}")
            self.update_status(item_id, "Searching Audio...")

            # --- Search Phase (Sequential) ---
            audio_candidates = []

            # 1. Tidal
            tidal_res = self.ingest.search_tidal(query, limit=5)
            audio_candidates.extend(tidal_res)

            # 2. Deezer
            if not audio_candidates: # Or combine? Prompt implied list from "music provider selected"
                deezer_res = self.ingest.search_deezer(query, limit=5)
                audio_candidates.extend(deezer_res)

            # 3. Soulseek (if enabled)
            # soulseek_res = self.ingest.search_soulseek(query, limit=5)
            # audio_candidates.extend(soulseek_res)

            selected_audio = None
            if self.interactive_mode.get():
                selection = self.ask_user_selection(query, audio_candidates, "Audio")

                if isinstance(selection, str) and selection.startswith("modify:"):
                    query = selection.split(":", 1)[1]
                    logger.info(f"Query modified to: {query}")
                    # Re-queue simple retry logic for this proof of concept
                    # Ideally loop back. For now, continue to next iteration of search logic logic
                    # But queue item is popped. We need to handle retry here or fail.
                    # Simple fail/skip for now to keep flow clean or we recurse.
                    self.update_status(item_id, "Query Modified - Retrying (re-add manually)")
                    continue
                elif selection == "skip" or not selection:
                    self.update_status(item_id, "Skipped by User")
                    continue
                else:
                    selected_audio = selection
            else:
                # Auto-select first
                if audio_candidates: selected_audio = audio_candidates[0]

            if not selected_audio:
                self.update_status(item_id, "Audio Not Found")
                continue

            # Fork Audio Task
            # We need to capture metadata now for Video search
            # Metadata from candidate
            metadata = {
                'artist': selected_audio.get('artist', artist),
                'title': selected_audio.get('title', song),
                'album': selected_audio.get('album', 'Unknown'),
                'date': '2023' # Default, update if available
            }
            # Refine query for video
            video_query = f"{metadata['artist']} - {metadata['title']}"

            # --- Video Search Phase ---
            self.update_status(item_id, "Searching Video...")
            video_candidates = self.ingest.search_youtube_video(video_query, limit=5)

            selected_video = None
            if self.interactive_mode.get():
                selection = self.ask_user_selection(video_query, video_candidates, "Video")
                if selection == "skip":
                    pass # Just skip video, keep audio
                elif isinstance(selection, dict):
                    selected_video = selection
            else:
                if video_candidates: selected_video = video_candidates[0]

            # --- Background Processing Fork ---
            # We submit a thread that acquires semaphore, downloads, transcribes, archives
            threading.Thread(target=self.process_item_background,
                             args=(item_id, selected_audio, selected_video, metadata)).start()

            # Loop immediately to next item in queue

        self.processing = False
        self.btn_start.config(state=tk.NORMAL)
        self.btn_stop.config(state=tk.DISABLED)
        logger.info("Queue main loop finished (background tasks may persist).")

    def process_item_background(self, item_id, audio_cand, video_cand, metadata):
        """Thread that handles heavy lifting with concurrency limit."""
        with self.download_semaphore:
            try:
                self.update_status(item_id, "Downloading Audio...")
                audio_path = None
                source = audio_cand['source']

                if source == 'Tidal':
                    audio_path = self.ingest.download_tidal(audio_cand['obj'], f"temp_{int(time.time())}.flac")
                elif source == 'Deezer':
                    audio_path = self.ingest.download_deezer(audio_cand['obj'], f"temp_{int(time.time())}.flac")

                if audio_path:
                    self.update_status(item_id, "Transcribing Audio...")
                    lrc_path = self.enrichment.transcribe_file(audio_path, 'lrc')
                    if lrc_path: self.enrichment.embed_lyrics(audio_path, lrc_path)

                    # Archive Audio
                    self.governance.archive_audio(audio_path, metadata)
                else:
                    logger.error(f"Audio download failed for {metadata['title']}")

                # Video Flow
                if video_cand:
                    self.update_status(item_id, "Downloading Video...")
                    video_path = self.ingest.download_youtube_video(video_cand['obj'], f"temp_vid_{int(time.time())}.mp4")

                    if video_path:
                        if audio_path:
                            self.update_status(item_id, "Syncing Metadata...")
                            self.enrichment.sync_metadata(audio_path, video_path)

                        self.update_status(item_id, "Transcribing Video...")
                        self.enrichment.transcribe_file(video_path, 'srt')

                        self.governance.archive_video(video_path, metadata)

                self.update_status(item_id, "Completed")

            except Exception as e:
                logger.error(f"Background process error: {e}")
                self.update_status(item_id, "Error")

if __name__ == "__main__":
    # Check for CLI arguments
    parser = argparse.ArgumentParser(description="Music Downloader CLI")
    parser.add_argument("--search", help="Query to search (Artist, Song, etc.)")
    parser.add_argument("--type", choices=["song", "artist", "album", "url"], default="song", help="Type of search")
    parser.add_argument("--limit", type=int, default=3, help="Limit number of items to process (for batch)")
    parser.add_argument("--no-gui", action="store_true", help="Run without GUI")

    args, unknown = parser.parse_known_args()

    if args.no_gui or args.search:
        # CLI Mode
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
        logger.info("Starting in CLI Mode")

        # Load Config directly
        config = {}
        try:
            with open("config.yaml", 'r') as f:
                config = yaml.safe_load(f)
        except Exception as e:
            logger.error(f"Config load error: {e}")

        app_logic = MusicDownloaderApp()
        # Bypass GUI loop, directly use logic
        # We need to adapt add_to_queue to work without GUI variables

        query = args.search
        if not query:
            logger.error("No search query provided.")
            sys.exit(1)

        logger.info(f"CLI Search: {query} ({args.type})")

        # Simulate adding to queue
        # Since logic is coupled with GUI treeview, we might need to refactor or mock the treeview
        # For this implementation, we will manually populate the job_queue and run process_queue

        # Expand based on type
        items_to_process = []
        if args.type == "url" or "http" in query:
             if "spotify" in query and ("playlist" in query or "album" in query):
                 tracks = app_logic.ingest.parse_spotify_playlist(query)
                 items_to_process.extend(tracks[:args.limit])
             else:
                 items_to_process.append(query) # Single URL
        elif args.type == "artist":
             tracks = app_logic.ingest.expand_artist(query)
             items_to_process.extend(tracks[:args.limit])
        elif args.type == "album":
             tracks = app_logic.ingest.expand_album(query)
             items_to_process.extend(tracks[:args.limit])
        else:
             items_to_process.append(query)

        # Queue items
        # We need to insert into treeview because process_queue reads from it
        # But treeview requires GUI.
        # Refactoring process_queue to take a data object instead of reading treeview is best.
        # But given constraints, we will override process_queue or mock treeview data.

        # Better: Create a headless processor method in MusicDownloaderApp

        # Mocking the tree data structure
        # item_id -> values
        mock_tree_data = {}

        for i, item in enumerate(items_to_process):
            # Parse simple "Artist - Song" or use raw
            parts = item.split(" - ")
            artist = parts[0].strip() if len(parts) > 1 else "?"
            song = parts[1].strip() if len(parts) > 1 else item

            item_id = f"cli_{i}"
            mock_tree_data[item_id] = {'values': [song, artist, "?", "Queued"]}
            app_logic.job_queue.put(item_id)

        # Patch app_logic.tree to behave like our mock
        class MockTree:
            def item(self, item_id, values=None):
                if values:
                    mock_tree_data[item_id]['values'] = values
                    logger.info(f"Status Update [{item_id}]: {values[3]}")
                return mock_tree_data.get(item_id, {})

        app_logic.tree = MockTree()
        app_logic.update_status = lambda item_id, status: app_logic.tree.item(item_id, values=(mock_tree_data[item_id]['values'][0], mock_tree_data[item_id]['values'][1], "?", status))

        # Disable interactive mode for CLI
        app_logic.interactive_mode.set(False)

        # Run processing
        logger.info(f"Processing {len(items_to_process)} items...")
        app_logic.stop_event.clear()
        app_logic.process_queue()
        logger.info("CLI Run Complete.")

    else:
        app = MusicDownloaderApp()
        app.mainloop()
