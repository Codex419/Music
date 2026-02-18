import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox, filedialog
import threading
import queue
import logging
import yaml
import time
import sys
import webbrowser
from pathlib import Path
from PIL import Image
import os

# Import Modules
from modules.ingest import Ingest
from modules.enrichment import Enrichment
from modules.governance import Governance
from modules.setup import check_model

# Try importing DnD (Optional with CTk, requires extra wrapping usually, we might stick to basic for now or use TkinterDnD wrapper)
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    # CustomCTkDnD logic would be needed, or mixing classes.
    # For stability in this refactor, we will base on CTk but maybe lose DND temporarily or use a known mixin.
    # Simple inheritance:
    class CTk(ctk.CTk, TkinterDnD.DnDWrapper):
        def __init__(self, *args, **kwargs):
            ctk.CTk.__init__(self, *args, **kwargs)
            self.TkdndVersion = TkinterDnD._require(self)
    DND_AVAILABLE = True
except ImportError:
    class CTk(ctk.CTk): pass
    DND_AVAILABLE = False

# Logging
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
            self.text_widget.see(tk.END)
        self.text_widget.after(100, self.poll)

class MusicDownloaderApp(CTk):
    def __init__(self):
        super().__init__()

        # Theme & Appearance
        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("blue")

        self.title("Music Downloader - Production Pipeline")
        self.geometry("1100x800")

        # Load Config
        self.config_path = "config.yaml"
        self.config = self.load_config()
        self.apply_config_theme()

        # Check Model
        check_model(self.config.get('ai', {}).get('model_size', 'medium'))

        # Initialize Modules
        self.ingest = Ingest(self.config)
        self.enrichment = Enrichment(self.config)
        self.governance = Governance(self.config)

        # Job Queue
        self.job_queue = queue.Queue()
        self.processing = False
        self.stop_event = threading.Event()
        self.download_semaphore = threading.Semaphore(1) # Default to 1

        # Interactive State
        self.interactive_mode = ctk.BooleanVar(value=False)
        self.user_decision = None
        self.user_input_event = threading.Event()

        # Layout Config
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Sidebar
        self.create_sidebar()

        # Main Content (Tabs)
        self.tabview = ctk.CTkTabview(self)
        self.tabview.grid(row=0, column=1, padx=10, pady=10, sticky="nsew")

        self.tab_queue = self.tabview.add("Job Queue")
        self.tab_settings = self.tabview.add("Settings")
        self.tab_help = self.tabview.add("Help")

        self.setup_queue_tab()
        self.setup_settings_tab()
        self.setup_help_tab()

        # Console
        self.console_box = ctk.CTkTextbox(self, height=150)
        self.console_box.grid(row=1, column=0, columnspan=2, padx=10, pady=10, sticky="ew")
        self.console_box.configure(state='disabled')

        # Logging Handler
        self.log_handler = TextHandler(self.console_box)
        logger.addHandler(self.log_handler)
        self.console_box.after(100, self.log_handler.poll)

    def create_sidebar(self):
        self.sidebar = ctk.CTkFrame(self, width=140, corner_radius=0)
        self.sidebar.grid(row=0, column=0, rowspan=1, sticky="nsew")
        self.sidebar.grid_rowconfigure(4, weight=1)

        logo = ctk.CTkLabel(self.sidebar, text="Music\nDownloader", font=ctk.CTkFont(size=20, weight="bold"))
        logo.grid(row=0, column=0, padx=20, pady=(20, 10))

        self.btn_start = ctk.CTkButton(self.sidebar, text="Start Processing", command=self.start_processing)
        self.btn_start.grid(row=1, column=0, padx=20, pady=10)

        self.btn_stop = ctk.CTkButton(self.sidebar, text="Stop", command=self.stop_processing, state="disabled", fg_color="red")
        self.btn_stop.grid(row=2, column=0, padx=20, pady=10)

        self.chk_interactive = ctk.CTkCheckBox(self.sidebar, text="Interactive Mode", variable=self.interactive_mode)
        self.chk_interactive.grid(row=3, column=0, padx=20, pady=10)

    def setup_queue_tab(self):
        # Grid config
        self.tab_queue.grid_columnconfigure(0, weight=1)
        self.tab_queue.grid_rowconfigure(1, weight=1)

        # Controls Frame
        ctrl_frame = ctk.CTkFrame(self.tab_queue)
        ctrl_frame.grid(row=0, column=0, padx=10, pady=10, sticky="ew")

        self.search_type_var = ctk.StringVar(value="Song")
        type_menu = ctk.CTkOptionMenu(ctrl_frame, variable=self.search_type_var, values=["Song", "Artist", "Album", "Url"], width=100)
        type_menu.pack(side="left", padx=5)

        self.entry_search = ctk.CTkEntry(ctrl_frame, placeholder_text="Search query or URL...", width=300)
        self.entry_search.pack(side="left", padx=5, fill="x", expand=True)
        self.entry_search.bind("<Return>", lambda e: self.add_to_queue())

        ctk.CTkButton(ctrl_frame, text="Add", width=60, command=self.add_to_queue).pack(side="left", padx=5)

        import_menu = ctk.CTkOptionMenu(ctrl_frame, values=["Import...", "Spotify/YouTube URL", "YouTube Cookies"],
                                        command=self.handle_import_menu, width=120)
        import_menu.set("Import...")
        import_menu.pack(side="left", padx=5)

        # Listbox/Treeview Replacement (CTkScrollableFrame)
        self.queue_frame = ctk.CTkScrollableFrame(self.tab_queue, label_text="Queue Items")
        self.queue_frame.grid(row=1, column=0, padx=10, pady=10, sticky="nsew")

        # We need to manually manage rows in CTkScrollableFrame
        self.queue_items = [] # List of widgets/data

    def add_queue_item_ui(self, title, artist, status="Queued"):
        item_frame = ctk.CTkFrame(self.queue_frame)
        item_frame.pack(fill="x", pady=2)

        lbl_info = ctk.CTkLabel(item_frame, text=f"{artist} - {title}", anchor="w")
        lbl_info.pack(side="left", padx=10, fill="x", expand=True)

        lbl_status = ctk.CTkLabel(item_frame, text=status, width=150, anchor="e")
        lbl_status.pack(side="right", padx=10)

        # Store ref to update status later
        item_data = {'frame': item_frame, 'lbl_status': lbl_status, 'info': (title, artist)}
        self.queue_items.append(item_data)

        # Add to processing queue
        self.job_queue.put(len(self.queue_items) - 1) # Put index

    def update_status(self, index, status):
        if 0 <= index < len(self.queue_items):
            self.after(0, lambda: self.queue_items[index]['lbl_status'].configure(text=status))

    def setup_settings_tab(self):
        # Scrollable Settings
        scroll = ctk.CTkScrollableFrame(self.tab_settings)
        scroll.pack(fill="both", expand=True)

        def add_section(title):
            lbl = ctk.CTkLabel(scroll, text=title, font=("", 16, "bold"), anchor="w")
            lbl.pack(fill="x", pady=(20, 5))

        def add_entry(label, key_path, secret=False):
            frame = ctk.CTkFrame(scroll)
            frame.pack(fill="x", pady=2)
            ctk.CTkLabel(frame, text=label, width=120, anchor="w").pack(side="left", padx=10)
            val = self.get_config_value(key_path)
            entry = ctk.CTkEntry(frame, show="*" if secret else "")
            entry.insert(0, str(val))
            entry.pack(side="right", fill="x", expand=True, padx=10)
            entry.bind("<FocusOut>", lambda e: self.set_config_value(key_path, entry.get()))
            return entry

        def add_combo(label, key_path, values):
            frame = ctk.CTkFrame(scroll)
            frame.pack(fill="x", pady=2)
            ctk.CTkLabel(frame, text=label, width=120, anchor="w").pack(side="left", padx=10)
            val = str(self.get_config_value(key_path))
            combo = ctk.CTkOptionMenu(frame, values=values, command=lambda v: self.set_config_value(key_path, v))
            combo.set(val)
            combo.pack(side="right", fill="x", expand=True, padx=10)

        # Paths
        add_section("Paths")
        add_entry("Music Dir", ['paths', 'music_dir'])
        add_entry("Video Dir", ['paths', 'video_dir'])

        # Tidal
        add_section("Tidal")
        add_entry("Token", ['tidal', 'token'], True)
        add_entry("Client ID", ['tidal', 'client_id'])
        add_entry("Client Secret", ['tidal', 'client_secret'], True)
        add_combo("Quality", ['tidal', 'quality'], ["LOW", "HIGH", "LOSSLESS", "HI_RES"])
        ctk.CTkButton(scroll, text="Login to Tidal", command=self.tidal_login_flow).pack(pady=10)

        # Deezer
        add_section("Deezer")
        add_entry("ARL", ['deezer', 'arl'], True)
        add_combo("Quality", ['deezer', 'quality'], ["MP3_128", "MP3_320", "FLAC"])

        # AI & Processing
        add_section("AI & Processing")
        add_combo("Model Size", ['ai', 'model_size'], ["tiny", "base", "small", "medium", "large-v2", "turbo"])
        add_combo("Device", ['ai', 'device'], ["cpu", "cuda", "auto"])
        add_entry("Concurrency", ['web_dl', 'concurrent_limit'])

        # Save
        ctk.CTkButton(scroll, text="Save Config", command=self.save_config, fg_color="green").pack(pady=20)

    def setup_help_tab(self):
        text = "Help & Instructions\n\n[Tokens]\nTidal: Use the Login button in settings.\nDeezer: Get 'arl' cookie from browser dev tools.\nYouTube: Use 'Get cookies.txt LOCALLY' extension."
        lbl = ctk.CTkLabel(self.tab_help, text=text, justify="left", anchor="nw")
        lbl.pack(fill="both", expand=True, padx=20, pady=20)

    # --- Logic Adapters ---

    def load_config(self):
        try:
            with open(self.config_path, 'r') as f: return yaml.safe_load(f)
        except: return {}

    def save_config(self):
        try:
            with open(self.config_path, 'w') as f: yaml.dump(self.config, f)
            messagebox.showinfo("Saved", "Configuration Saved")
        except Exception as e: messagebox.showerror("Error", str(e))

    def get_config_value(self, keys):
        val = self.config
        for k in keys: val = val.get(k, {})
        return val if not isinstance(val, dict) else ""

    def set_config_value(self, keys, value):
        d = self.config
        for k in keys[:-1]: d = d.setdefault(k, {})
        d[keys[-1]] = value
        if keys == ['ui', 'theme']: self.apply_config_theme()

    def apply_config_theme(self):
        theme = self.get_config_value(['ui', 'theme'])
        ctk.set_appearance_mode(theme if theme in ["Dark", "Light"] else "Dark")

    def handle_import_menu(self, choice):
        if choice == "Spotify/YouTube URL":
            self.import_url()
        elif choice == "YouTube Cookies":
            self.show_cookies_help()

    def add_to_queue(self, query=None):
        if not query: query = self.entry_search.get()
        if not query: return
        self.entry_search.delete(0, 'end')

        search_type = self.search_type_var.get()
        if "http" in query: search_type = "Url"

        # Process expansion in thread to not block UI
        threading.Thread(target=self._expand_and_enqueue, args=(query, search_type)).start()

    def _expand_and_enqueue(self, query, search_type):
        items = []
        if search_type == "Url":
            if "spotify" in query and ("playlist" in query or "album" in query):
                items = self.ingest.parse_spotify_playlist(query)
            else:
                meta = self.ingest.parse_spotify_url(query)
                if meta: items = [f"{meta['artist']} - {meta['title']}"]
                else: items = [query] # Fallback
        elif search_type == "Artist":
            items = self.ingest.expand_artist(query)
        elif search_type == "Album":
            items = self.ingest.expand_album(query)
        else:
            items = [query]

        for item in items:
            # Parse artist/song
            parts = item.split(" - ", 1)
            artist = parts[0] if len(parts)>1 else "?"
            song = parts[1] if len(parts)>1 else item
            self.after(0, lambda t=song, a=artist: self.add_queue_item_ui(t, a))

    def import_url(self):
        url = ctk.CTkInputDialog(text="Enter URL:", title="Import").get_input()
        if url: self.add_to_queue(url)

    def show_cookies_help(self):
        messagebox.showinfo("Cookies", "Use 'Get cookies.txt LOCALLY' extension and save to app folder.")

    def tidal_login_flow(self):
        # Reuse previous logic but adapted for CTk/Threading
        threading.Thread(target=self._tidal_login_bg, daemon=True).start()

    def _tidal_login_bg(self):
        try:
            import tidalapi
            session = tidalapi.Session()
            login = session.get_link_login()
            url = getattr(login, 'verification_uri_complete', None) or 'https://link.tidal.com'
            code = getattr(login, 'user_code', 'Unknown')

            self.after(0, lambda: self.show_tidal_popup(url, code))
            session.process_link_login(login)
            if session.check_login():
                self.after(0, lambda: self.on_tidal_login_success(session))
        except Exception as e:
            logger.error(f"Tidal Login Error: {e}")

    def show_tidal_popup(self, url, code):
        top = ctk.CTkToplevel(self)
        top.geometry("400x300")
        ctk.CTkLabel(top, text=f"Code: {code}", font=("", 20)).pack(pady=20)
        ctk.CTkButton(top, text="Open Link", command=lambda: webbrowser.open(url)).pack(pady=10)

    def on_tidal_login_success(self, session):
        self.set_config_value(['tidal', 'access_token'], session.access_token)
        self.set_config_value(['tidal', 'refresh_token'], session.refresh_token)
        self.set_config_value(['tidal', 'expiry_time'], session.expiry_time.timestamp())
        self.set_config_value(['tidal', 'token_type'], session.token_type)
        self.save_config()
        messagebox.showinfo("Tidal", "Login Successful")

    def start_processing(self):
        if self.processing: return
        self.processing = True
        self.stop_event.clear()
        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")

        limit = int(self.get_config_value(['web_dl', 'concurrent_limit']) or 1)
        self.download_semaphore = threading.Semaphore(limit)

        threading.Thread(target=self.process_queue, daemon=True).start()

    def stop_processing(self):
        self.stop_event.set()
        self.processing = False
        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        logger.info("Stopping...")

    def process_queue(self):
        while not self.stop_event.is_set():
            try:
                # Non-blocking get to allow stop check
                idx = self.job_queue.get(timeout=1)
            except queue.Empty:
                continue

            item = self.queue_items[idx]
            title, artist = item['info']
            query = f"{artist} - {title}" if artist != "?" else title

            self.update_status(idx, "Searching...")

            # Search Logic
            candidates = self.ingest.search_tidal(query)
            if not candidates: candidates = self.ingest.search_deezer(query)

            # Interactive?
            selected = None
            if self.interactive_mode.get():
                selected = self.ask_user_selection(query, candidates)
            else:
                selected = candidates[0] if candidates else None

            if not selected:
                self.update_status(idx, "Not Found")
                continue

            # Video Search
            vid_query = f"{selected['artist']} - {selected['title']}"
            vid_cands = self.ingest.search_youtube_video(vid_query)
            vid_selected = vid_cands[0] if vid_cands else None

            # Submit to Background
            threading.Thread(target=self.process_item_background, args=(idx, selected, vid_selected)).start()

    def ask_user_selection(self, query, candidates):
        self.user_decision = None
        self.user_input_event.clear()

        def show():
            top = ctk.CTkToplevel(self)
            top.geometry("600x600")
            scroll = ctk.CTkScrollableFrame(top)
            scroll.pack(fill="both", expand=True)

            for cand in candidates:
                f = ctk.CTkFrame(scroll)
                f.pack(fill="x", pady=5)
                ctk.CTkLabel(f, text=f"{cand['artist']} - {cand['title']}").pack(side="left")
                ctk.CTkButton(f, text="Select", width=60,
                              command=lambda c=cand: [setattr(self, 'user_decision', c), self.user_input_event.set(), top.destroy()]).pack(side="right")

            ctk.CTkButton(top, text="Skip", fg_color="red",
                          command=lambda: [self.user_input_event.set(), top.destroy()]).pack(pady=10)

        self.after(0, show)
        self.user_input_event.wait()
        return self.user_decision

    def process_item_background(self, idx, audio_cand, video_cand):
        files_created = []
        with self.download_semaphore:
            try:
                if self.stop_event.is_set(): return

                # Audio
                self.update_status(idx, f"DL Audio ({audio_cand['source']})")
                audio_path = f"temp_{int(time.time())}.flac"
                files_created.append(audio_path)

                if audio_cand['source'] == 'Tidal':
                    self.ingest.download_tidal(audio_cand['obj'], audio_path)
                elif audio_cand['source'] == 'Deezer':
                    self.ingest.download_deezer(audio_cand['obj'], audio_path)

                if self.stop_event.is_set(): raise InterruptedError()

                # Transcribe Audio
                self.update_status(idx, "Transcribing Audio")
                lrc_path = self.enrichment.transcribe_file(audio_path, 'lrc')
                if lrc_path: files_created.append(lrc_path)

                # Video
                if video_cand:
                    self.update_status(idx, "DL Video")
                    vid_path = f"temp_vid_{int(time.time())}.mp4"
                    files_created.append(vid_path)
                    self.ingest.download_youtube_video(video_cand['obj'], vid_path)

                    if self.stop_event.is_set(): raise InterruptedError()

                    self.update_status(idx, "Transcribing Video")
                    self.enrichment.transcribe_file(vid_path, 'srt')
                    self.enrichment.sync_metadata(audio_path, vid_path)

                    # Archive
                    meta = {'artist': audio_cand['artist'], 'title': audio_cand['title'], 'album': audio_cand['album'], 'date': '2023'}
                    self.governance.archive_video(vid_path, meta)

                # Archive Audio
                meta = {'artist': audio_cand['artist'], 'title': audio_cand['title'], 'album': audio_cand['album'], 'date': '2023'}
                self.governance.archive_audio(audio_path, meta)

                self.update_status(idx, "Complete")

            except InterruptedError:
                self.update_status(idx, "Stopped")
                logger.info("Cleaning up incomplete files...")
                for f in files_created:
                    try:
                        if os.path.exists(f):
                            os.remove(f)
                            logger.info(f"Deleted incomplete file: {f}")
                    except Exception as clean_err:
                        logger.error(f"Failed to delete {f}: {clean_err}")
            except Exception as e:
                logger.error(f"Task Failed: {e}")
                self.update_status(idx, "Error")
                # Clean up on error too if desired
                for f in files_created:
                    try:
                        if os.path.exists(f): os.remove(f)
                    except: pass

if __name__ == "__main__":
    app = MusicDownloaderApp()
    app.mainloop()
