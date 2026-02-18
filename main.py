import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox, filedialog
import threading
import queue
import logging
import yaml
import time
import os
import webbrowser
from pathlib import Path

# Modules
from modules.ingest import Ingest
from modules.enrichment import Enrichment
from modules.governance import Governance

# Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger()

class TextHandler(logging.Handler):
    def __init__(self, text_widget):
        logging.Handler.__init__(self)
        self.text_widget = text_widget
        self.queue = queue.Queue()

    def emit(self, record):
        self.queue.put(self.format(record))

    def poll(self):
        while not self.queue.empty():
            msg = self.queue.get()
            self.text_widget.configure(state='normal')
            self.text_widget.insert(tk.END, msg + '\n')
            self.text_widget.configure(state='disabled')
            self.text_widget.see(tk.END)
        self.text_widget.after(100, self.poll)

class PipelineManager:
    def __init__(self, app, config, ingest, enrichment, governance):
        self.app = app
        self.config = config
        self.ingest = ingest
        self.enrichment = enrichment
        self.governance = governance

        # Queues
        self.download_queue = queue.Queue()
        self.transcription_queue = queue.Queue()

        # Threads
        self.download_threads = []
        self.transcription_thread = None
        self.stop_event = threading.Event()

        # Limits
        self.dl_concurrency = 5
        self.trans_concurrency = 1

    def start(self):
        self.stop_event.clear()

        # Start Download Workers
        for i in range(self.dl_concurrency):
            t = threading.Thread(target=self.download_worker, name=f"DL-Worker-{i}", daemon=True)
            t.start()
            self.download_threads.append(t)

        # Start Transcription Worker
        self.transcription_thread = threading.Thread(target=self.transcription_worker, name="AI-Worker", daemon=True)
        self.transcription_thread.start()

    def stop(self):
        self.stop_event.set()

    def add_job(self, item):
        self.download_queue.put(item)
        self.app.update_queue_ui()

    def download_worker(self):
        while not self.stop_event.is_set():
            try:
                item = self.download_queue.get(timeout=1)
                self.process_download(item)
                self.download_queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Download Worker Error: {e}")

    def transcription_worker(self):
        while not self.stop_event.is_set():
            try:
                item = self.transcription_queue.get(timeout=1)
                self.process_transcription(item)
                self.transcription_queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Transcription Worker Error: {e}")

    def process_download(self, item):
        """
        Download Audio -> Download Video -> Push to AI.
        Supports skipping if 'target' is specified or files exist.
        """
        item_id = item['id']
        metadata = item['metadata']

        self.app.update_status(item_id, "Checking Files")

        # --- Audio Step ---
        audio_path = None
        # Check Governance for existing
        existing_audio = self.governance.check_exists(metadata, 'audio')
        if existing_audio:
            logger.info(f"Audio exists: {existing_audio}")
            audio_path = existing_audio
            self.app.update_status(item_id, "Audio Exists")
        else:
            # Download
            self.app.update_status(item_id, f"DL Audio ({metadata.get('source', '?')})")
            temp_audio = f"temp_audio_{item_id}_{int(time.time())}.flac"

            if metadata.get('source') == 'Tidal':
                audio_path = self.ingest.download_tidal(item['obj'], temp_audio)
            elif metadata.get('source') == 'Deezer':
                audio_path = self.ingest.download_deezer(item['obj'], temp_audio)

            if not audio_path:
                logger.warning(f"Audio download failed for {metadata['title']}")
                # If audio fails, we might still process video? Or abort?
                # Abort for now as metadata sync needs audio.
                self.app.update_status(item_id, "Audio Failed")
                return

        item['audio_path'] = audio_path

        # --- Video Step ---
        # Only if we want video (default yes)
        self.app.update_status(item_id, "Searching Video")

        # Select best video
        video_cand = self.ingest.search_and_select_best_video(metadata['artist'], metadata['title'])

        video_path = None
        if video_cand:
            # Check existing
            # We assume video title matches audio metadata for archival, so check generic
            existing_video = self.governance.check_exists(metadata, 'video')
            if existing_video:
                video_path = existing_video
                self.app.update_status(item_id, "Video Exists")
            else:
                self.app.update_status(item_id, "DL Video")
                temp_video = f"temp_video_{item_id}_{int(time.time())}.mp4"
                video_path = self.ingest.download_youtube_video(video_cand, temp_video)
        else:
            logger.info("No suitable video found.")

        item['video_path'] = video_path

        # Push to AI Queue
        self.app.update_status(item_id, "Queued for AI")
        self.transcription_queue.put(item)

    def process_transcription(self, item):
        item_id = item['id']
        audio_path = item.get('audio_path')
        video_path = item.get('video_path')
        metadata = item['metadata']

        # --- Audio Enrichment ---
        if audio_path and os.path.exists(audio_path):
            self.app.update_status(item_id, "Transcribing Audio")
            lrc_path = self.enrichment.transcribe_file(audio_path, 'lrc')
            if lrc_path:
                self.enrichment.embed_lyrics(audio_path, lrc_path)

            # Archive Audio
            self.app.update_status(item_id, "Archiving Audio")
            final_audio = self.governance.archive_audio(audio_path, metadata)
            item['final_audio'] = final_audio

        # --- Video Enrichment ---
        if video_path and os.path.exists(video_path):
            self.app.update_status(item_id, "Transcribing Video")
            self.enrichment.transcribe_file(video_path, 'srt')

            # Sync Metadata (Audio -> Video)
            # We use the raw download path or archived path?
            # Use archived audio path if available (has correct tags?) or raw
            src_audio = item.get('final_audio') or audio_path
            if src_audio and os.path.exists(src_audio):
                self.app.update_status(item_id, "Syncing Metadata")
                self.enrichment.transfer_metadata(src_audio, video_path)

            # Archive Video
            self.app.update_status(item_id, "Archiving Video")
            self.governance.archive_video(video_path, metadata)

        self.app.update_status(item_id, "Complete", 1.0)


class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        # Setup
        ctk.set_appearance_mode("Dark")
        self.title("Music Downloader Pro")
        self.geometry("1200x800")

        self.config = self.load_config()
        self.init_modules()

        # Layout
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.create_sidebar()
        self.create_main_view()
        self.create_console()

        # Pipeline
        self.pipeline = PipelineManager(self, self.config, self.ingest, self.enrichment, self.governance)

        # Data
        self.queue_items = [] # list of dicts: {id, widget, status_label, progress, metadata}
        self.item_counter = 0

    def load_config(self):
        try:
            with open("config.yaml") as f: return yaml.safe_load(f)
        except: return {}

    def save_config(self):
        try:
            with open("config.yaml", 'w') as f: yaml.dump(self.config, f)
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

    def init_modules(self):
        self.ingest = Ingest(self.config)
        self.enrichment = Enrichment(self.config)
        self.governance = Governance(self.config)

    def create_sidebar(self):
        sidebar = ctk.CTkFrame(self, width=140, corner_radius=0)
        sidebar.grid(row=0, column=0, rowspan=2, sticky="nsew")

        ctk.CTkLabel(sidebar, text="Music\nDownloader", font=("", 20, "bold")).pack(pady=20)

        ctk.CTkButton(sidebar, text="Start", command=self.start_pipeline).pack(pady=10, padx=20)
        ctk.CTkButton(sidebar, text="Scan Library", command=self.scan_library).pack(pady=10, padx=20)
        ctk.CTkButton(sidebar, text="Import Playlist", command=self.import_playlist).pack(pady=10, padx=20)
        ctk.CTkButton(sidebar, text="Import YouTube", command=self.import_youtube_reverse).pack(pady=10, padx=20)

    def create_main_view(self):
        self.tabview = ctk.CTkTabview(self)
        self.tabview.grid(row=0, column=1, padx=10, pady=10, sticky="nsew")

        self.tab_queue = self.tabview.add("Queue")
        self.tab_settings = self.tabview.add("Settings")

        # Queue List
        self.queue_scroll = ctk.CTkScrollableFrame(self.tab_queue, label_text="Jobs")
        self.queue_scroll.pack(fill="both", expand=True, padx=5, pady=5)

        # Add Search Bar to Queue Tab
        frame = ctk.CTkFrame(self.tab_queue)
        frame.pack(fill="x", padx=5, pady=5, before=self.queue_scroll)
        self.entry_search = ctk.CTkEntry(frame, placeholder_text="Search Song...")
        self.entry_search.pack(side="left", fill="x", expand=True, padx=5)
        ctk.CTkButton(frame, text="Add", width=60, command=self.add_manual).pack(side="left", padx=5)

        # Setup Settings
        self.setup_settings_tab()

    def setup_settings_tab(self):
        scroll = ctk.CTkScrollableFrame(self.tab_settings)
        scroll.pack(fill="both", expand=True)

        def add_entry(label, key_path, secret=False):
            frame = ctk.CTkFrame(scroll)
            frame.pack(fill="x", pady=2)
            ctk.CTkLabel(frame, text=label, width=120, anchor="w").pack(side="left", padx=10)
            val = self.get_config_value(key_path)
            entry = ctk.CTkEntry(frame, show="*" if secret else "")
            entry.insert(0, str(val))
            entry.pack(side="right", fill="x", expand=True, padx=10)
            entry.bind("<FocusOut>", lambda e: self.set_config_value(key_path, entry.get()))

        # Paths
        ctk.CTkLabel(scroll, text="Paths", font=("", 16, "bold"), anchor="w").pack(fill="x", pady=(20, 5))
        add_entry("Music Dir", ['paths', 'music_dir'])
        add_entry("Video Dir", ['paths', 'video_dir'])

        # Tidal
        ctk.CTkLabel(scroll, text="Tidal", font=("", 16, "bold"), anchor="w").pack(fill="x", pady=(20, 5))
        add_entry("Token", ['tidal', 'token'], True)
        add_entry("Client ID", ['tidal', 'client_id'])
        add_entry("Client Secret", ['tidal', 'client_secret'], True)
        ctk.CTkButton(scroll, text="Login Tidal", command=self.tidal_login_flow).pack(pady=10)

        # Deezer
        ctk.CTkLabel(scroll, text="Deezer", font=("", 16, "bold"), anchor="w").pack(fill="x", pady=(20, 5))
        add_entry("ARL", ['deezer', 'arl'], True)

        # AI
        ctk.CTkLabel(scroll, text="AI", font=("", 16, "bold"), anchor="w").pack(fill="x", pady=(20, 5))
        add_entry("Model Size", ['ai', 'model_size'])
        add_entry("Device", ['ai', 'device'])

        # Save
        ctk.CTkButton(scroll, text="Save Config", command=self.save_config, fg_color="green").pack(pady=20)

    def tidal_login_flow(self):
        try:
            import tidalapi
            session = tidalapi.Session()
            login = session.get_link_login()
            url = getattr(login, 'verification_uri_complete', None) or 'https://link.tidal.com'
            code = getattr(login, 'user_code', 'Unknown')

            top = ctk.CTkToplevel(self)
            top.geometry("400x200")
            ctk.CTkLabel(top, text=f"Code: {code}", font=("", 20)).pack(pady=20)
            ctk.CTkButton(top, text="Open Link", command=lambda: webbrowser.open(url)).pack(pady=10)

            # Simple polling in thread
            def _poll():
                try:
                    session.process_link_login(login)
                    if session.check_login():
                        self.set_config_value(['tidal', 'access_token'], session.access_token)
                        self.set_config_value(['tidal', 'refresh_token'], session.refresh_token)
                        self.set_config_value(['tidal', 'expiry_time'], session.expiry_time.timestamp())
                        self.save_config()
                        messagebox.showinfo("Tidal", "Login Successful")
                        top.destroy()
                except Exception as e:
                    logger.error(f"Login poll error: {e}")

            threading.Thread(target=_poll, daemon=True).start()

        except Exception as e:
            messagebox.showerror("Error", str(e))

    def create_console(self):
        self.console = ctk.CTkTextbox(self, height=150)
        self.console.grid(row=1, column=1, padx=10, pady=10, sticky="ew")
        self.console.configure(state='disabled')

        handler = TextHandler(self.console)
        logger.addHandler(handler)
        self.console.after(100, handler.poll)

    # --- Actions ---
    def start_pipeline(self):
        self.pipeline.start()
        logger.info("Pipeline Started.")

    def add_manual(self):
        query = self.entry_search.get()
        if not query: return
        self.entry_search.delete(0, 'end')

        threading.Thread(target=self._resolve_and_add, args=(query,)).start()

    def _resolve_and_add(self, query):
        logger.info(f"Resolving: {query}")
        # Default to Tidal search
        cands = self.ingest.search_tidal(query)
        if not cands: cands = self.ingest.search_deezer(query)

        if cands:
            self.add_to_queue_ui(cands[0])
        else:
            logger.warning(f"No results for {query}")

    def import_playlist(self):
        url = ctk.CTkInputDialog(title="Import Playlist", text="URL:").get_input()
        if url:
            threading.Thread(target=self._process_playlist, args=(url,)).start()

    def _process_playlist(self, url):
        items = self.ingest.parse_playlist(url)
        logger.info(f"Found {len(items)} items in playlist.")
        for item in items:
            self._resolve_and_add(item)

    def import_youtube_reverse(self):
        # Reverse Logic: Video Playlist -> Audio
        url = ctk.CTkInputDialog(title="YouTube Playlist", text="URL:").get_input()
        if url:
            threading.Thread(target=self._process_yt_reverse, args=(url,)).start()

    def _process_yt_reverse(self, url):
        titles = self.ingest.parse_playlist(url)
        logger.info(f"Found {len(titles)} videos in playlist.")
        for title in titles:
            cands = self.ingest.reverse_search_audio(title)
            if cands:
                self.add_to_queue_ui(cands[0])
            else:
                logger.warning(f"Could not find audio for video: {title}")

    def scan_library(self):
        threading.Thread(target=self._scan_library_bg).start()

    def _scan_library_bg(self):
        music_path = Path(self.config['paths']['music_dir'])
        logger.info(f"Scanning {music_path}...")

        for root, dirs, files in os.walk(music_path):
            for file in files:
                if file.lower().endswith(('.flac', '.mp3')):
                    # Create pseudo-metadata from filename/tags
                    # For now assume structure matches: Artist/Album/Artist - Title.ext
                    path = Path(os.path.join(root, file))
                    try:
                        # Reverse logic from path
                        # Parent = Album [Year], Parent.Parent = Artist
                        # Filename = Artist - Title.ext
                        artist = path.parent.parent.name
                        filename_base = path.stem
                        if " - " in filename_base:
                            title = filename_base.split(" - ", 1)[1]
                        else:
                            title = filename_base

                        meta = {'artist': artist, 'title': title, 'album': path.parent.name.split(' [')[0]}

                        # Check gaps
                        lrc = path.with_suffix('.lrc')
                        video_exists = self.governance.check_exists(meta, 'video')

                        if not lrc.exists() or not video_exists:
                            self._resolve_and_add(f"{artist} - {title}")

                    except Exception as e:
                        logger.error(f"Scan error on {file}: {e}")

    # --- UI Management ---
    def add_to_queue_ui(self, metadata):
        self.item_counter += 1
        item_id = self.item_counter

        def _add():
            f = ctk.CTkFrame(self.queue_scroll)
            f.pack(fill="x", pady=2)

            ctk.CTkLabel(f, text=f"{metadata['artist']} - {metadata['title']}", anchor="w").pack(side="left", padx=10)
            status_lbl = ctk.CTkLabel(f, text="Queued", width=100)
            status_lbl.pack(side="right", padx=10)

            prog = ctk.CTkProgressBar(f)
            prog.set(0)
            prog.pack(side="right", padx=10)

            item = {
                'id': item_id,
                'metadata': metadata,
                'widget': f,
                'status_label': status_lbl,
                'progress': prog,
                'obj': metadata.get('obj') # Tidal/Deezer track object
            }
            self.queue_items.append(item)
            self.pipeline.add_job(item)

        self.after(0, _add)

    def update_status(self, item_id, status, progress=None):
        def _upd():
            for item in self.queue_items:
                if item['id'] == item_id:
                    item['status_label'].configure(text=status)
                    if progress is not None:
                        item['progress'].set(progress)
                    break
        self.after(0, _upd)

    def update_queue_ui(self):
        # Triggered when queue changes, mostly handled by add/update
        pass

if __name__ == "__main__":
    app = App()
    app.mainloop()
