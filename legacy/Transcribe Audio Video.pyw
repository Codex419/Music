import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext, Menu, Listbox, Scrollbar
import os
import glob
import threading
import time
import math
import sys
import queue
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.lines import Line2D # For spectrogram progress line
import subprocess
import webbrowser

# --- Dependency Checks ---
# (Checks remain the same)
try: import librosa, librosa.display
except ImportError: messagebox.showerror("Dependency Error", "Please install plotting libraries:\npip install librosa numpy matplotlib"); sys.exit(1)
try: from tkinterdnd2 import DND_FILES, TkinterDnD
except ImportError: messagebox.showerror("Dependency Error", "Please install TkinterDnD2:\npip install tkinterdnd2-universal"); sys.exit(1)
try: from faster_whisper import WhisperModel, format_timestamp
except ImportError: messagebox.showerror("Dependency Error", "Please install faster-whisper:\npip install faster-whisper"); sys.exit(1)
try:
    import torch
    PYTORCH_AVAILABLE = True
    try: CUDA_AVAILABLE = torch.cuda.is_available()
    except Exception: CUDA_AVAILABLE = False
except ImportError: PYTORCH_AVAILABLE = False; CUDA_AVAILABLE = False; print("PyTorch not found. GPU unavailable.")

# --- Constants ---
SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
MODEL_DOWNLOAD_DIR = os.path.join(SCRIPT_DIR, "Audio Models")
AUDIO_EXTENSIONS = ["*.wav", "*.mp3", "*.flac", "*.aac", "*.m4a", "*.ogg"]
VIDEO_EXTENSIONS = ["*.mp4", "*.mkv", "*.avi", "*.mov", "*.wmv", "*.flv"]
SUPPORTED_EXTENSIONS = AUDIO_EXTENSIONS + VIDEO_EXTENSIONS
MODELS = { # Model descriptions... (concise)
    "tiny": "Tiny (~39M). Fast, low accuracy.", "tiny.en": "Tiny English-only (~39M).",
    "base": "Base (~74M). Balanced.", "base.en": "Base English-only (~74M).",
    "small": "Small (~244M). Good accuracy.", "small.en": "Small English-only (~244M).",
    "medium": "Medium (~769M). High accuracy.", "medium.en": "Medium English-only (~769M).",
    "large-v1": "Large v1 (~1.55B). Very high accuracy.", "large-v2": "Large v2 (~1.55B). Improved.",
    "large-v3": "Large v3 (~1.55B). Best accuracy.",
    "distil-large-v2": "Distilled L-v2 (~750M). Faster large.",
    "distil-medium.en": "Distilled M-en (~450M). Faster medium.en.",
    "distil-small.en": "Distilled S-en (~150M). Faster small.en."
}
MODEL_SIZES = list(MODELS.keys())
QUANTIZED_MODEL_SUFFIXES = ["int8", "int8_float16", "int8_bfloat16", "int16", "float16"]
COMPUTE_TYPES_CPU = ["default", "auto", "int8", "int16", "float32"]
COMPUTE_TYPES_CUDA = ["default", "auto", "float16", "int8_float16", "int8", "bfloat16", "int8_bfloat16"]
COMPUTE_TYPES_ROCM = ["default", "auto", "float16", "int8_float16", "int8"]

# --- Theme Colors ---
DARK_BG = "#1e1e1e"; DARK_FG = "#e0e0e0"; DARK_WIDGET_BG = "#2d2d2d"
DARK_SELECT_BG = "#3a3d41"; DARK_BUTTON = "#007acc"; DARK_BUTTON_FG = "#ffffff"
DARK_BUTTON_ACTIVE = "#005f9e"; STOP_BUTTON_BG = "#c74e4e"; STOP_BUTTON_ACTIVE = "#a13e3e"
DARK_TEXT_AREA = "#252526"; DARK_PROGRESS_BAR = "#9b59b6"; DARK_PROGRESS_BG = "#3a3d41" # Purple Progress Bar
DARK_BORDER = "#4a4d51"; ACCENT_COLOR = "#9b59b6"; PLOT_BG = "#2d2d2d" # Purple Accent
LISTBOX_BG = "#252526"; LISTBOX_FG = "#e0e0e0"; LISTBOX_SELECT_BG = ACCENT_COLOR; LISTBOX_SELECT_FG = DARK_BG

# Status indicators
STATUS_PENDING = "⏳"
STATUS_PROCESSING = "⚙️"
STATUS_COMPLETED = "✅"
STATUS_SKIPPED = "⚠️"
STATUS_ERROR = "❌"

# --- Helper Functions ---
# (segments_to_srt, vtt, txt, lrc and format_eta remain the same)
def segments_to_srt(segments):
    srt_content = ""
    for i, segment in enumerate(segments):
        start_time = format_timestamp(segment.start, always_include_hours=True, decimal_marker=',')
        end_time = format_timestamp(segment.end, always_include_hours=True, decimal_marker=',')
        text = segment.text.strip().replace('-->', '->')
        srt_content += f"{i + 1}\n{start_time} --> {end_time}\n{text}\n\n"
    return srt_content
def segments_to_vtt(segments): # Kept just in case
    vtt_content = "WEBVTT\n\n"; text = ""
    for segment in segments:
        start_time = format_timestamp(segment.start, always_include_hours=True, decimal_marker='.')
        end_time = format_timestamp(segment.end, always_include_hours=True, decimal_marker='.')
        text = segment.text.strip().replace('-->', '->')
        vtt_content += f"{start_time} --> {end_time}\n{text}\n\n"
    return vtt_content
def segments_to_txt(segments): return "\n".join(segment.text.strip() for segment in segments)
def segments_to_lrc(segments):
    lrc_content = ""; text = ""
    for segment in segments:
        total_seconds = segment.start; minutes = int(total_seconds // 60); seconds = int(total_seconds % 60)
        centiseconds = int((total_seconds - int(total_seconds)) * 100)
        lrc_timestamp = f"[{minutes:02d}:{seconds:02d}.{centiseconds:02d}]"
        text = segment.text.strip()
        if text: lrc_content += f"{lrc_timestamp}{text}\n"
    return lrc_content
def format_eta(seconds):
    if seconds < 0 or not math.isfinite(seconds): return "--:--"
    seconds = int(seconds); hours = seconds // 3600; minutes = (seconds % 3600) // 60; secs = seconds % 60
    if hours > 0: return f"{hours}h {minutes:02d}m {secs:02d}s"
    elif minutes > 0: return f"{minutes}m {secs:02d}s"
    else: return f"{secs}s"

# --- Tooltip Class ---
class ToolTip:
    def __init__(self, widget, status_label, text='widget info'):
        self.widget = widget; self.status_label = status_label; self.text = text
        self.widget.bind("<Enter>", self.enter); self.widget.bind("<Leave>", self.leave); self.widget.bind("<ButtonPress>", self.leave)
    def enter(self, event=None): self.status_label.config(text=self.text)
    def leave(self, event=None): self.status_label.config(text="")

# --- GUI Class ---
class WhisperGUI:
    def __init__(self, master):
        self.master = master
        master.title("Codex Audio Transcriber V1")
        master.geometry("1000x800") # Increased size for file list

        # --- Variables ---
        self.input_mode = tk.StringVar(value="single"); self.input_path = tk.StringVar()
        self.model_size = tk.StringVar(value="large-v2")
        self.quantization = tk.StringVar(value="")
        self.device = tk.StringVar() # Default set below
        self.compute_type = tk.StringVar() # Default set below
        self.vad_filter = tk.BooleanVar(value=False); self.beam_size = tk.IntVar(value=5)
        self.overwrite_output = tk.BooleanVar(value=False) # *** NEW: Overwrite flag ***
        self.model_description = tk.StringVar(value=MODELS.get(self.model_size.get(), "..."))

        # --- Processing State ---
        self.processing_active = False; self.processing_thread = None; self.stop_requested = 0
        self.file_start_time = None; self.batch_start_time = None
        self.completed_file_times = []; self.total_batch_files = 0; self.processed_batch_files = 0
        self.file_data = {} # Dictionary to store file info: {filepath: {status, type, tree_id, duration}}

        # --- Visualizer Variables ---
        self.fig, self.ax = None, None; self.canvas, self.canvas_widget = None, None
        self.visualizer_frame = None
        self.spectrogram_line = None # Handle for the progress line

        # --- Detect Devices & Set Defaults ---
        self.available_devices = ["cpu"]
        if CUDA_AVAILABLE:
            self.available_devices.append("cuda"); default_device = "cuda"; default_compute = "float16"
        else:
            default_device = "cpu"; default_compute = "int8" if "int8" in COMPUTE_TYPES_CPU else "auto"
            print("\n--- CUDA GPU NOT DETECTED ---\n...(Guidance print)... \nProceeding with CPU only.\n")
        self.device.set(default_device); self.compute_type.set(default_compute)

        # --- Tooltip Texts ---
        self.tooltips = { # Tooltips remain largely the same
            "input_mode_single": "Process a single audio/video file (drag & drop enabled).",
            "input_mode_batch": "Process all supported files in a directory and its subfolders (drag & drop enabled).",
            "input_path": "Path to the file/directory. You can also drag & drop here.",
            "input_browse": "Browse for the input file or directory.",
            "model_size": "Select Whisper model. Models downloaded to 'Audio Models' folder.",
            "model_description_area": "Shows a description of the selected model size.",
            "quantization": "Select model quantization (e.g., int8). Reduces size/memory, may speed up CPU inference.",
            "device": f"Processing device: 'cuda' (NVIDIA GPU - {'Available' if CUDA_AVAILABLE else 'NOT DETECTED!'}) or 'cpu'.",
            "compute_type": "Data type for computation (e.g., float16, int8). Affects speed/memory.",
            "beam_size": "Decoding beams (Default: 5). Higher values may increase accuracy but are slower.",
            "vad_filter": "Voice Activity Detection. Filters non-speech parts (silence/noise).",
            "overwrite_output": "If checked, process files even if SRT/LRC output already exists, overwriting the old file.", # *** NEW Tooltip ***
            "output_info": "Output: TXT (always) + SRT (for video) / LRC (for audio) saved in same directory as input.",
            "start_stop_button": "Start processing / Request stop.",
            "file_progress_label": "Progress for the current file (based on timestamps).",
            "batch_progress_label": "Overall batch progress and estimated time remaining (ETA).",
            "file_progress_bar": "Visual indicator for current file processing.",
            "batch_progress_bar": "Overall progress for batch processing.",
            "visualizer_area": "Displays a Mel spectrogram of the current audio file.",
            "file_status_list": "Shows files to be processed and their status.",
            "status_bar": "Shows tooltips for the control you are hovering over."
        }
        self.tooltips["device"] = f"Processing device: 'cuda' (NVIDIA GPU - {'Available' if CUDA_AVAILABLE else 'NOT DETECTED!'}) or 'cpu'." # Update dynamically

        # --- Style & Window Setup ---
        self.style = ttk.Style(master); self.setup_dark_theme()
        master.configure(bg=DARK_BG)
        master.protocol("WM_DELETE_WINDOW", self.on_closing)
        master.columnconfigure(0, weight=1); master.rowconfigure(0, weight=1)

        # --- Ensure Model Directory Exists ---
        try: os.makedirs(MODEL_DOWNLOAD_DIR, exist_ok=True); print(f"Models dir: {MODEL_DOWNLOAD_DIR}")
        except OSError as e: print(f"Error creating model dir '{MODEL_DOWNLOAD_DIR}': {e}"); messagebox.showerror("Directory Error", f"Could not create model directory:\n{MODEL_DOWNLOAD_DIR}")

        # --- Menu Bar ---
        self.menu_bar = Menu(master)
        master.config(menu=self.menu_bar)
        tools_menu = Menu(self.menu_bar, tearoff=0, background=DARK_WIDGET_BG, foreground=DARK_FG)
        self.menu_bar.add_cascade(label="Tools", menu=tools_menu)
        tools_menu.add_command(label="Install Core Dependencies", command=self.run_install_core_deps_thread)
        tools_menu.add_command(label="Check/Install PyTorch (GPU Support)", command=self.check_pytorch_install)
        tools_menu.add_separator()
        tools_menu.add_command(label="Open Model Folder", command=self.open_model_folder)

        # --- Main Frame Layout (Configure Scaling) ---
        self.main_frame = ttk.Frame(master, padding="10", style="Futuristic.TFrame")
        self.main_frame.grid(row=0, column=0, sticky="nsew")
        self.main_frame.columnconfigure(0, weight=3); self.main_frame.columnconfigure(1, weight=2) # Controls vs Visualizer ratio
        self.main_frame.rowconfigure(4, weight=1) # File list row expands

        # --- Left Panel (Controls) ---
        left_panel = ttk.Frame(self.main_frame, style="Futuristic.TFrame")
        left_panel.grid(row=0, column=0, rowspan=3, sticky="nsew", padx=(0, 10)) # Span rows for controls
        left_panel.columnconfigure(0, weight=1)

        # --- Drag & Drop Setup ---
        self.main_frame.drop_target_register(DND_FILES)
        self.main_frame.dnd_bind('<<Drop>>', self.handle_drop)

        # --- Input Frame ---
        input_frame = ttk.LabelFrame(left_panel, text="📁 Input Source", padding=(10, 5), style="Futuristic.TLabelframe")
        input_frame.grid(row=0, column=0, columnspan=3, sticky="ew", padx=5, pady=(5, 10)); input_frame.columnconfigure(1, weight=1)
        rb_single = ttk.Radiobutton(input_frame, text="Single File", variable=self.input_mode, value="single", command=self.update_input_label, style="Futuristic.TRadiobutton"); rb_single.grid(row=0, column=0, padx=5, pady=2, sticky="w")
        rb_batch = ttk.Radiobutton(input_frame, text="Batch Directory (incl. Subfolders)", variable=self.input_mode, value="batch", command=self.update_input_label, style="Futuristic.TRadiobutton"); rb_batch.grid(row=0, column=1, columnspan=2, padx=5, pady=2, sticky="w")
        self.input_label_text = tk.StringVar(value="Select File:"); lbl_input = ttk.Label(input_frame, textvariable=self.input_label_text, style="Futuristic.TLabel"); lbl_input.grid(row=1, column=0, padx=5, pady=2, sticky="w")
        self.input_entry = ttk.Entry(input_frame, textvariable=self.input_path, width=40, style="Futuristic.TEntry"); self.input_entry.grid(row=1, column=1, padx=5, pady=2, sticky="ew")
        btn_browse_input = ttk.Button(input_frame, text="Browse...", command=self.browse_input, style="Accent.TButton"); btn_browse_input.grid(row=1, column=2, padx=5, pady=2)

        # --- Model Frame ---
        model_frame = ttk.LabelFrame(left_panel, text="🧠 Model Configuration", padding=(10, 5), style="Futuristic.TLabelframe")
        model_frame.grid(row=1, column=0, columnspan=3, sticky="ew", padx=5, pady=5); model_frame.columnconfigure(1, weight=1); model_frame.columnconfigure(3, weight=1)
        lbl_model = ttk.Label(model_frame, text="Model Size:", style="Futuristic.TLabel"); lbl_model.grid(row=0, column=0, padx=5, pady=2, sticky="w")
        self.model_combo = ttk.Combobox(model_frame, textvariable=self.model_size, values=MODEL_SIZES, width=18, style="Futuristic.TCombobox"); self.model_combo.grid(row=0, column=1, padx=5, pady=2, sticky="ew"); self.model_combo.bind("<<ComboboxSelected>>", self.update_model_description)
        lbl_quant = ttk.Label(model_frame, text="Quantization:", style="Futuristic.TLabel"); lbl_quant.grid(row=0, column=2, padx=5, pady=2, sticky="w")
        self.quant_combo = ttk.Combobox(model_frame, textvariable=self.quantization, values=[""] + QUANTIZED_MODEL_SUFFIXES, width=12, style="Futuristic.TCombobox"); self.quant_combo.grid(row=0, column=3, padx=5, pady=2, sticky="ew"); self.quant_combo.set("")
        lbl_device = ttk.Label(model_frame, text="Device:", style="Futuristic.TLabel"); lbl_device.grid(row=1, column=0, padx=5, pady=2, sticky="w")
        self.device_combo = ttk.Combobox(model_frame, textvariable=self.device, values=self.available_devices, state="readonly", width=8, style="Futuristic.TCombobox"); self.device_combo.grid(row=1, column=1, padx=5, pady=2, sticky="ew"); self.device_combo.bind("<<ComboboxSelected>>", self.update_compute_types)
        lbl_compute = ttk.Label(model_frame, text="Compute Type:", style="Futuristic.TLabel"); lbl_compute.grid(row=1, column=2, padx=5, pady=2, sticky="w")
        self.compute_combo = ttk.Combobox(model_frame, textvariable=self.compute_type, state="readonly", width=12, style="Futuristic.TCombobox"); self.compute_combo.grid(row=1, column=3, padx=5, pady=2, sticky="ew")
        self.model_desc_label = ttk.Label(model_frame, textvariable=self.model_description, wraplength=450, justify=tk.LEFT, style="Desc.TLabel"); self.model_desc_label.grid(row=2, column=0, columnspan=4, padx=5, pady=(5,2), sticky="ew")
        self.update_compute_types(); self.update_model_description() # Initialize

        # --- Processing Frame (Simplified + Overwrite) ---
        proc_frame = ttk.LabelFrame(left_panel, text="⚙️ Processing Options", padding=(10, 5), style="Futuristic.TLabelframe")
        proc_frame.grid(row=2, column=0, columnspan=3, sticky="ew", padx=5, pady=5); proc_frame.columnconfigure(1, weight=1); proc_frame.columnconfigure(3, weight=1)
        lbl_beam = ttk.Label(proc_frame, text="Beam Size:", style="Futuristic.TLabel"); lbl_beam.grid(row=0, column=0, padx=5, pady=2, sticky="w") # Changed row to 0
        self.beam_spinbox = ttk.Spinbox(proc_frame, from_=1, to=100, textvariable=self.beam_size, width=5, style="Futuristic.TSpinbox"); self.beam_spinbox.grid(row=0, column=1, padx=5, pady=2, sticky="w") # Changed row to 0
        self.vad_check = ttk.Checkbutton(proc_frame, text="VAD Filter", variable=self.vad_filter, style="Futuristic.TCheckbutton"); self.vad_check.grid(row=0, column=2, padx=15, pady=2, sticky="w") # Changed row to 0
        # *** NEW: Overwrite Checkbox ***
        self.overwrite_check = ttk.Checkbutton(proc_frame, text="Overwrite Existing Output", variable=self.overwrite_output, style="Futuristic.TCheckbutton"); self.overwrite_check.grid(row=1, column=0, columnspan=3, padx=5, pady=(5,2), sticky="w") # New row for checkbox

        # --- Output Frame (Simplified) ---
        output_frame = ttk.LabelFrame(left_panel, text="💾 Output", padding=(10, 5), style="Futuristic.TLabelframe")
        output_frame.grid(row=3, column=0, columnspan=3, sticky="ew", padx=5, pady=5); output_frame.columnconfigure(0, weight=1)
        self.output_info_label = ttk.Label(output_frame, text="Output: TXT (always) + SRT (for video) / LRC (for audio)\nSaved in the same directory as the input file.", style="Desc.TLabel", justify=tk.LEFT)
        self.output_info_label.grid(row=0, column=0, padx=5, pady=5, sticky="w")

        # --- Action & Progress Frame ---
        action_frame = ttk.Frame(self.main_frame, padding=(10, 5), style="Futuristic.TFrame")
        action_frame.grid(row=3, column=0, columnspan=2, sticky="ew", pady=5) # Below controls/viz
        action_frame.columnconfigure(1, weight=1)
        self.file_progress_label = ttk.Label(action_frame, text="File Progress:", style="Futuristic.TLabel"); self.file_progress_label.grid(row=0, column=0, sticky="w", padx=(5,0))
        self.batch_progress_label = ttk.Label(action_frame, text="Batch Progress:", style="Futuristic.TLabel")
        self.file_progress_bar = ttk.Progressbar(action_frame, orient=tk.HORIZONTAL, length=150, mode='determinate', style="Futuristic.Horizontal.TProgressbar"); self.file_progress_bar.grid(row=0, column=1, sticky="ew", padx=5, pady=2)
        self.batch_progress_bar = ttk.Progressbar(action_frame, orient=tk.HORIZONTAL, length=300, mode='determinate', style="Futuristic.Horizontal.TProgressbar")
        self.start_stop_button = ttk.Button(action_frame, text="🚀 Start Transcription", command=self.toggle_processing, style="Accent.TButton", width=20)
        self.start_stop_button.grid(row=0, column=2, rowspan=2, padx=10, pady=5, sticky="e")

        # --- File Status List Frame (Replaces Log) ---
        filelist_frame = ttk.LabelFrame(self.main_frame, text="📊 File Queue / Status", padding=(10, 5), style="Futuristic.TLabelframe")
        filelist_frame.grid(row=4, column=0, columnspan=2, sticky="nsew", padx=5, pady=5) # Row 4, spans 2 cols
        filelist_frame.columnconfigure(0, weight=1); filelist_frame.rowconfigure(0, weight=1) # Make treeview expand

        # Create Treeview
        self.file_tree = ttk.Treeview(filelist_frame, columns=("filename", "type", "status", "progress"), show="headings", style="Futuristic.Treeview")
        self.file_tree.heading("filename", text="Filename")
        self.file_tree.heading("type", text="Type", anchor=tk.CENTER)
        self.file_tree.heading("status", text="Status", anchor=tk.CENTER)
        self.file_tree.heading("progress", text="Progress", anchor=tk.E)
        self.file_tree.column("filename", anchor=tk.W, width=400, stretch=tk.YES)
        self.file_tree.column("type", anchor=tk.CENTER, width=60, stretch=tk.NO)
        self.file_tree.column("status", anchor=tk.CENTER, width=100, stretch=tk.NO)
        self.file_tree.column("progress", anchor=tk.E, width=80, stretch=tk.NO)
        # Add Scrollbars
        tree_scrollbar_y = ttk.Scrollbar(filelist_frame, orient=tk.VERTICAL, command=self.file_tree.yview, style="Vertical.TScrollbar")
        tree_scrollbar_x = ttk.Scrollbar(filelist_frame, orient=tk.HORIZONTAL, command=self.file_tree.xview, style="Horizontal.TScrollbar")
        self.file_tree.configure(yscrollcommand=tree_scrollbar_y.set, xscrollcommand=tree_scrollbar_x.set)
        # Grid Treeview and Scrollbars
        self.file_tree.grid(row=0, column=0, sticky="nsew")
        tree_scrollbar_y.grid(row=0, column=1, sticky="ns")
        tree_scrollbar_x.grid(row=1, column=0, columnspan=2, sticky="ew")

        # --- Right Panel (Visualizer) ---
        self.visualizer_outer_frame = ttk.LabelFrame(self.main_frame, text="🔊 Audio Spectrogram", padding=(10, 5), style="Futuristic.TLabelframe")
        self.visualizer_outer_frame.grid(row=0, column=1, rowspan=3, sticky="nsew", padx=(10, 5), pady=5) # Spans rows 0-2
        self.visualizer_outer_frame.columnconfigure(0, weight=1); self.visualizer_outer_frame.rowconfigure(0, weight=1)
        self.visualizer_frame = ttk.Frame(self.visualizer_outer_frame, style="Futuristic.TFrame", relief=tk.SUNKEN, borderwidth=1); self.visualizer_frame.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)

        # --- Status Bar ---
        self.status_bar = ttk.Label(self.main_frame, text="Hover over an option for details.", anchor=tk.W, relief=tk.FLAT, style="Status.TLabel", padding=(5, 3))
        self.status_bar.grid(row=5, column=0, columnspan=2, sticky="ew", padx=5, pady=(5,0)) # Row 5

        # --- Initialize Plot and Tooltips ---
        self.init_plot()
        self.assign_tooltips() # Assign tooltips AFTER all widgets are created
        self.update_input_label()


    def setup_dark_theme(self):
        """Configures ttk styles for a futuristic dark theme."""
        # (Theme setup remains the same)
        self.style.theme_use('clam')
        self.style.configure('.', background=DARK_BG, foreground=DARK_FG, fieldbackground=DARK_WIDGET_BG, bordercolor=DARK_BORDER, lightcolor=DARK_BG, darkcolor=DARK_BG, font=('Segoe UI', 9))
        self.style.map('.', background=[('active', DARK_SELECT_BG), ('disabled', DARK_WIDGET_BG)], foreground=[('disabled', '#777777')])
        self.style.configure("Futuristic.TFrame", background=DARK_BG)
        self.style.configure("Futuristic.TLabel", background=DARK_BG, foreground=DARK_FG, font=('Segoe UI', 9))
        self.style.configure("Desc.TLabel", background=DARK_BG, foreground="#a0a0a0", font=('Segoe UI', 8, 'italic'))
        self.style.configure("Futuristic.TLabelframe", background=DARK_BG, foreground=DARK_FG, bordercolor=DARK_BORDER, relief=tk.SOLID, borderwidth=1)
        self.style.configure("Futuristic.TLabelframe.Label", background=DARK_BG, foreground=ACCENT_COLOR, font=('Segoe UI', 10, 'bold')) # Purple Title
        self.style.configure("Accent.TButton", background=ACCENT_COLOR, foreground=DARK_BG, bordercolor=DARK_BORDER, padding=6, font=('Segoe UI', 9, 'bold')) # Purple Button
        self.style.map("Accent.TButton", background=[('active', '#af7ac5'), ('pressed', '#af7ac5'), ('disabled', DARK_WIDGET_BG)], foreground=[('disabled', '#777777')]) # Lighter purple active
        self.style.configure("Stop.TButton", background=STOP_BUTTON_BG, foreground=DARK_BUTTON_FG, bordercolor=DARK_BORDER, padding=6, font=('Segoe UI', 9, 'bold'))
        self.style.map("Stop.TButton", background=[('active', STOP_BUTTON_ACTIVE), ('pressed', STOP_BUTTON_ACTIVE), ('disabled', DARK_WIDGET_BG)], foreground=[('disabled', '#777777')])
        self.style.configure("Futuristic.TEntry", fieldbackground=DARK_WIDGET_BG, foreground=DARK_FG, insertcolor=DARK_FG, bordercolor=DARK_BORDER, borderwidth=1)
        self.style.map("Futuristic.TEntry", fieldbackground=[('focus', DARK_WIDGET_BG)], bordercolor=[('focus', ACCENT_COLOR)]) # Purple focus border
        self.style.configure("Futuristic.TCombobox", fieldbackground=DARK_WIDGET_BG, background=DARK_WIDGET_BG, foreground=DARK_FG, arrowcolor=DARK_FG, bordercolor=DARK_BORDER, borderwidth=1)
        self.style.map("Futuristic.TCombobox", fieldbackground=[('readonly', DARK_WIDGET_BG)], selectbackground=[('focus', DARK_SELECT_BG), ('!focus', DARK_SELECT_BG)], selectforeground=[('focus', DARK_FG), ('!focus', DARK_FG)], bordercolor=[('focus', ACCENT_COLOR)]) # Purple focus border
        self.master.option_add('*TCombobox*Listbox.background', DARK_WIDGET_BG); self.master.option_add('*TCombobox*Listbox.foreground', DARK_FG); self.master.option_add('*TCombobox*Listbox.selectBackground', ACCENT_COLOR); self.master.option_add('*TCombobox*Listbox.selectForeground', DARK_BG) # Purple selection
        self.style.configure("Futuristic.TSpinbox", fieldbackground=DARK_WIDGET_BG, background=DARK_WIDGET_BG, foreground=DARK_FG, arrowcolor=DARK_FG, bordercolor=DARK_BORDER, borderwidth=1)
        self.style.map("Futuristic.TSpinbox", bordercolor=[('focus', ACCENT_COLOR)]) # Purple focus border
        self.style.configure("Futuristic.TCheckbutton", background=DARK_BG, foreground=DARK_FG, indicatorcolor=DARK_WIDGET_BG, padding=3)
        self.style.map("Futuristic.TCheckbutton", indicatorcolor=[('selected', ACCENT_COLOR), ('active', DARK_SELECT_BG)], background=[('active', DARK_BG)]) # Purple indicator
        self.style.configure("Futuristic.TRadiobutton", background=DARK_BG, foreground=DARK_FG, indicatorcolor=DARK_WIDGET_BG, padding=3)
        self.style.map("Futuristic.TRadiobutton", indicatorcolor=[('selected', ACCENT_COLOR), ('active', DARK_SELECT_BG)], background=[('active', DARK_BG)]) # Purple indicator
        self.style.configure("Futuristic.Horizontal.TProgressbar", troughcolor=DARK_PROGRESS_BG, background=DARK_PROGRESS_BAR, bordercolor=DARK_BORDER, thickness=10) # Purple bar
        self.style.configure("Status.TLabel", background=DARK_BG, foreground="#a0a0a0", font=('Segoe UI', 8))
        # Treeview Style
        self.style.configure("Futuristic.Treeview", background=LISTBOX_BG, foreground=LISTBOX_FG, fieldbackground=LISTBOX_BG, rowheight=25) # Adjust row height if needed
        self.style.map("Futuristic.Treeview", background=[('selected', LISTBOX_SELECT_BG)], foreground=[('selected', LISTBOX_SELECT_FG)]) # Purple selection
        self.style.configure("Futuristic.Treeview.Heading", background=DARK_WIDGET_BG, foreground=DARK_FG, font=('Segoe UI', 9, 'bold'), relief=tk.FLAT)
        self.style.map("Futuristic.Treeview.Heading", background=[('active', DARK_SELECT_BG)])
        # Scrollbar Style
        self.style.configure("Vertical.TScrollbar", background=DARK_WIDGET_BG, troughcolor=DARK_BG, bordercolor=DARK_BORDER, arrowcolor=DARK_FG, relief=tk.FLAT)
        self.style.map("Vertical.TScrollbar", background=[('active', DARK_SELECT_BG)])
        self.style.configure("Horizontal.TScrollbar", background=DARK_WIDGET_BG, troughcolor=DARK_BG, bordercolor=DARK_BORDER, arrowcolor=DARK_FG, relief=tk.FLAT)
        self.style.map("Horizontal.TScrollbar", background=[('active', DARK_SELECT_BG)])


    def assign_tooltips(self):
        """Assigns tooltips to the relevant widgets."""
        if not hasattr(self, 'status_bar'): print("ERROR: Status bar not initialized!"); return
        ToolTip(self.input_entry.master.children['!radiobutton'], self.status_bar, self.tooltips["input_mode_single"])
        ToolTip(self.input_entry.master.children['!radiobutton2'], self.status_bar, self.tooltips["input_mode_batch"])
        ToolTip(self.input_entry, self.status_bar, self.tooltips["input_path"])
        ToolTip(self.input_entry.master.children['!button'], self.status_bar, self.tooltips["input_browse"])
        ToolTip(self.model_combo, self.status_bar, self.tooltips["model_size"])
        ToolTip(self.model_desc_label, self.status_bar, self.tooltips["model_description_area"])
        ToolTip(self.quant_combo, self.status_bar, self.tooltips["quantization"])
        ToolTip(self.device_combo, self.status_bar, self.tooltips["device"])
        ToolTip(self.compute_combo, self.status_bar, self.tooltips["compute_type"])
        ToolTip(self.beam_spinbox, self.status_bar, self.tooltips["beam_size"])
        ToolTip(self.vad_check, self.status_bar, self.tooltips["vad_filter"])
        ToolTip(self.overwrite_check, self.status_bar, self.tooltips["overwrite_output"]) # *** NEW Tooltip ***
        ToolTip(self.output_info_label, self.status_bar, self.tooltips["output_info"])
        ToolTip(self.start_stop_button, self.status_bar, self.tooltips["start_stop_button"])
        ToolTip(self.file_progress_label, self.status_bar, self.tooltips["file_progress_label"])
        ToolTip(self.batch_progress_label, self.status_bar, self.tooltips["batch_progress_label"])
        ToolTip(self.file_progress_bar, self.status_bar, self.tooltips["file_progress_bar"])
        ToolTip(self.batch_progress_bar, self.status_bar, self.tooltips["batch_progress_bar"])
        ToolTip(self.visualizer_frame, self.status_bar, self.tooltips["visualizer_area"])
        ToolTip(self.file_tree, self.status_bar, self.tooltips["file_status_list"]) # Tooltip for treeview
        ToolTip(self.status_bar, self.status_bar, self.tooltips["status_bar"])


    def init_plot(self):
        """Initializes the matplotlib figure and canvas."""
        # (Plot initialization remains the same)
        try:
            self.fig, self.ax = plt.subplots(facecolor=PLOT_BG, constrained_layout=True)
            self.ax.set_facecolor(PLOT_BG)
            self.ax.tick_params(axis='x', colors=DARK_FG, labelsize=8); self.ax.tick_params(axis='y', colors=DARK_FG, labelsize=8)
            for spine in self.ax.spines.values(): spine.set_color(DARK_BORDER)
            self.ax.text(0.5, 0.5, 'Spectrogram will appear here', ha='center', va='center', transform=self.ax.transAxes, color=DARK_FG)
            self.ax.set_xticks([]); self.ax.set_yticks([])
            self.canvas = FigureCanvasTkAgg(self.fig, master=self.visualizer_frame)
            self.canvas_widget = self.canvas.get_tk_widget()
            self.canvas_widget.pack(fill=tk.BOTH, expand=True)
            # Initialize the progress line (invisible initially)
            self.spectrogram_line = Line2D([0, 0], [0, 1], transform=self.ax.get_xaxis_transform(), color='red', linestyle='--', linewidth=1, visible=False)
            self.ax.add_line(self.spectrogram_line)
            self.canvas.draw()
        except Exception as e:
            self._log_message_gui(f"❌ Error initializing plot: {e}") # Log error
            if self.canvas_widget: self.canvas_widget.pack_forget()
            if self.fig: plt.close(self.fig)
            ttk.Label(self.visualizer_frame, text=f"Plot Error:\n{e}", style="Desc.TLabel").pack(padx=10, pady=10)


    def clear_plot(self):
        """Clears the plot area and hides progress line."""
        # (Clear plot remains the same)
        if self.ax:
            self.ax.clear()
            self.ax.text(0.5, 0.5, 'Spectrogram cleared', ha='center', va='center', transform=self.ax.transAxes, color=DARK_FG)
            self.ax.set_xticks([]); self.ax.set_yticks([])
            self.ax.set_xlabel(""); self.ax.set_ylabel(""); self.ax.set_title("")
            # Re-add the line handle but keep it invisible
            if self.spectrogram_line:
                self.spectrogram_line.set_visible(False)
                if self.spectrogram_line not in self.ax.lines: # Avoid adding multiple times
                     self.ax.add_line(self.spectrogram_line)
            if self.canvas: self.canvas.draw_idle()

    def update_spectrogram_line(self, current_time):
        """Updates the position of the progress line on the spectrogram."""
        if self.ax and self.spectrogram_line and self.canvas:
            # Ensure line is visible
            self.spectrogram_line.set_visible(True)
            # Set x-data for the vertical line
            self.spectrogram_line.set_xdata([current_time, current_time])
            # Redraw only the necessary parts (blitting might be faster but more complex)
            self.canvas.draw_idle()

    def hide_spectrogram_line(self):
        """Hides the progress line."""
        if self.spectrogram_line and self.canvas:
            self.spectrogram_line.set_visible(False)
            self.canvas.draw_idle()


    def plot_spectrogram(self, audio_path):
        """Initiates spectrogram generation in a separate thread."""
        # (Plot spectrogram remains the same)
        plot_thread = threading.Thread(target=self._plot_spectrogram_thread, args=(audio_path,), daemon=True)
        plot_thread.start()

    def _plot_spectrogram_thread(self, audio_path):
        """Internal method: Loads audio, computes spectrogram (runs in thread)."""
        # (Internal plot thread has improved error handling)
        try:
            self._log_message_gui(f"   Generating spectrogram for {os.path.basename(audio_path)}...")
            try: y, sr = librosa.load(audio_path, sr=None, mono=True)
            except Exception as load_err:
                self._log_message_gui(f"   ❌ Error loading audio: {load_err}")
                if "audioread" in str(load_err) or "backend" in str(load_err): self._log_message_gui("      (Hint: FFmpeg might be missing or not in PATH for video files.)")
                if self.master.winfo_exists(): self.master.after(0, self.clear_plot); return
            if y is None or len(y) == 0:
                self._log_message_gui("   ⚠️ Audio could not be loaded or is empty.")
                if self.master.winfo_exists(): self.master.after(0, self.clear_plot); return
            try: S = librosa.feature.melspectrogram(y=y, sr=sr, n_fft=2048, hop_length=512, n_mels=128); S_dB = librosa.power_to_db(S, ref=np.max)
            except Exception as spec_err:
                self._log_message_gui(f"   ❌ Error computing spectrogram: {spec_err}")
                # *** FIXED SYNTAX ERROR HERE ***
                if self.master.winfo_exists():
                    self.master.after(0, self.clear_plot)
                return # Stop if computation failed

            def _do_plot_main_thread():
                if not self.ax or not self.canvas: return
                try:
                    self.ax.clear() # Clear previous plot content
                    img = librosa.display.specshow(S_dB, sr=sr, hop_length=512, x_axis='time', y_axis='mel', ax=self.ax, cmap='magma')
                    self.ax.set_title(f'Mel Spectrogram: {os.path.basename(audio_path)}', color=DARK_FG, fontsize=9)
                    self.ax.set_xlabel("Time (s)", color=DARK_FG, fontsize=8); self.ax.set_ylabel("Frequency (Mel)", color=DARK_FG, fontsize=8)
                    # Re-initialize and add the line after clearing axes
                    self.spectrogram_line = Line2D([0, 0], [0, 1], transform=self.ax.get_xaxis_transform(), color='red', linestyle='--', linewidth=1, visible=False)
                    self.ax.add_line(self.spectrogram_line)
                    self.canvas.draw_idle()
                except Exception as plot_err: self._log_message_gui(f"   ❌ Error during plotting: {plot_err}"); self.clear_plot()
            if self.master.winfo_exists(): self.master.after(0, _do_plot_main_thread)
            self._log_message_gui("   ✅ Spectrogram generated.")
        except Exception as e:
            self._log_message_gui(f"   ❌ Unexpected error in spectrogram thread: {e}")
            # *** FIXED SYNTAX ERROR HERE ***
            if self.master.winfo_exists():
                self.master.after(0, self.clear_plot)


    def update_status_threadsafe(self, message):
        """Updates the status in the Treeview or logs general messages."""
        # Check if message indicates a file status update
        status_prefixes = {
            STATUS_PROCESSING: ("processing", DARK_FG),
            STATUS_COMPLETED: ("completed", "#77cc77"),
            STATUS_SKIPPED: ("skipped", "#ccaa77"),
            STATUS_ERROR: ("error", "#cc7777"),
            STATUS_PENDING: ("pending", DARK_FG)
        }
        is_file_status = False
        for prefix, (status_type, color) in status_prefixes.items():
            if message.startswith(prefix):
                is_file_status = True
                filepath = message[len(prefix):].strip()
                if filepath in self.file_data:
                    tree_id = self.file_data[filepath]['tree_id']
                    # Schedule Treeview update in main thread
                    if self.master.winfo_exists():
                        self.master.after(0, lambda id=tree_id, p=prefix, fp=filepath, c=color: self._update_treeview_status(id, p, fp, c))
                else: # Log normally if filepath not found (shouldn't happen often)
                    is_file_status = False
                break

        if not is_file_status:
            # Log general messages to console/debug for now
             if self.master.winfo_exists():
                 self.master.after(0, lambda msg=message: self._log_message_gui(msg))


    def _update_treeview_status(self, tree_id, status_prefix, filepath, color):
        """Updates a specific item's status in the Treeview (MUST run in main thread)."""
        try:
            # Update the status column (index '2' which is the 3rd column)
            self.file_tree.item(tree_id, values=(
                os.path.basename(filepath), # Keep filename
                self.file_data[filepath]['type'], # Keep type
                status_prefix, # Update status symbol
                self.file_tree.set(tree_id, "progress") # Keep progress value
            ))
            # Apply color tag (optional, requires tag_configure)
            # self.file_tree.item(tree_id, tags=(status_type,))
            # self.file_tree.tag_configure(status_type, foreground=color)
            # Ensure the updated item is visible
            self.file_tree.see(tree_id)
        except tk.TclError:
            pass # Item might not exist if list cleared rapidly
        except KeyError:
             pass # Filepath might not be in dict if cleared rapidly

    def _update_treeview_progress(self, tree_id, progress_percent):
         """Updates a specific item's progress value in the Treeview (MUST run in main thread)."""
         try:
             # Update the progress column (index '3' which is the 4th column)
             self.file_tree.set(tree_id, "progress", f"{progress_percent:.1f}%")
         except tk.TclError:
             pass # Item might not exist

    def _log_message_gui(self, message):
        """Logs a general message to console (or future dedicated log)."""
        print(f"LOG: {message}")


    def update_model_description(self, event=None):
        """Updates the model description label."""
        self.model_description.set(MODELS.get(self.model_size.get(), "Select a model..."))

    def update_input_label(self):
        """Updates input label and batch progress visibility."""
        mode = self.input_mode.get()
        if mode == "single":
            self.input_label_text.set("Select File:")
            self.batch_progress_label.grid_remove(); self.batch_progress_bar.grid_remove()
            self.start_stop_button.grid(row=0, column=2, rowspan=1)
        else: # batch mode
            self.input_label_text.set("Select Dir:")
            self.batch_progress_label.grid(row=1, column=0, sticky="w", padx=(5,0), pady=(5,0))
            self.batch_progress_bar.grid(row=1, column=1, sticky="ew", padx=5, pady=(5,2))
            self.start_stop_button.grid(row=0, column=2, rowspan=2)
        if not self.processing_active:
            self.input_path.set(""); self.clear_plot()
            # Clear Treeview when input changes
            for item in self.file_tree.get_children():
                self.file_tree.delete(item)
            self.file_data.clear()


    def handle_drop(self, event):
        """Handles files/folders dropped onto the main frame."""
        if self.processing_active: self._log_message_gui("⚠️ Cannot change input while processing."); return
        raw_path = event.data.strip();
        if raw_path.startswith('{') and raw_path.endswith('}'): raw_path = raw_path[1:-1]
        dropped_path = raw_path.strip()
        if not dropped_path: self._log_message_gui("⚠️ Drop event with no path."); return
        self._log_message_gui(f"ℹ️ Item dropped: {dropped_path}")
        if os.path.isdir(dropped_path):
            self.input_mode.set("batch"); self.input_path.set(dropped_path)
            self.update_input_label(); self._log_message_gui("   Detected directory -> Batch mode.")
            self.populate_file_list() # Populate list on drop
        elif os.path.isfile(dropped_path):
            _, ext = os.path.splitext(dropped_path)
            is_supported = any(ext.lower() == sup_ext[1:].lower() for sup_ext in SUPPORTED_EXTENSIONS)
            if is_supported:
                 self.input_mode.set("single"); self.input_path.set(dropped_path)
                 self.update_input_label(); self._log_message_gui("   Detected file -> Single File mode.")
                 self.plot_spectrogram(dropped_path)
                 self.populate_file_list() # Populate list for single file
            else:
                 self._log_message_gui(f"   ⚠️ Dropped file type not supported: {ext}")
                 messagebox.showwarning("Unsupported File", f"File type ('{ext}') not supported.")
                 self.input_path.set(""); self.clear_plot()
        else:
            self._log_message_gui(f"   ⚠️ Dropped item not file/directory: {dropped_path}")
            messagebox.showerror("Drop Error", f"Cannot process dropped item:\n{dropped_path}")
            self.input_path.set(""); self.clear_plot()

    def update_compute_types(self, event=None):
        """Updates available compute types based on selected device."""
        device = self.device.get(); current_compute = self.compute_type.get(); valid_types = []
        default_compute = "auto"
        if device == "cuda": valid_types = COMPUTE_TYPES_CUDA; default_compute = "float16"
        elif device == "rocm": valid_types = COMPUTE_TYPES_ROCM; default_compute = "float16"
        else: valid_types = COMPUTE_TYPES_CPU; default_compute = "int8" if "int8" in valid_types else "auto"
        self.compute_combo['values'] = valid_types
        if not current_compute or current_compute not in valid_types: self.compute_type.set(default_compute)
        if self.compute_type.get() not in valid_types:
             if valid_types: self.compute_type.set(valid_types[0])
             else: self.compute_type.set("")

    def browse_input(self):
        """Handles browsing for input file or directory."""
        if self.processing_active: self._log_message_gui("⚠️ Cannot change input while processing."); return
        mode = self.input_mode.get(); last_dir = os.path.dirname(self.input_path.get()) if self.input_path.get() else "/"
        if mode == "single":
            fts = [("Audio/Video", " ".join(ext[1:] for ext in SUPPORTED_EXTENSIONS)), ("All", "*.*")]
            fp = filedialog.askopenfilename(title="Select Input File", filetypes=fts, initialdir=last_dir)
            if fp: self.input_path.set(fp); self.plot_spectrogram(fp); self.populate_file_list()
        else:
            dp = filedialog.askdirectory(title="Select Input Directory", initialdir=last_dir)
            if dp: self.input_path.set(dp); self.clear_plot(); self.populate_file_list()

    def populate_file_list(self):
         """Scans input path and populates the Treeview."""
         self.file_tree.delete(*self.file_tree.get_children()) # Clear existing items
         self.file_data.clear()
         input_path = self.input_path.get()
         mode = self.input_mode.get()
         files_to_scan = []

         if not input_path or not os.path.exists(input_path):
             return # Nothing to populate

         if mode == "single" and os.path.isfile(input_path):
             files_to_scan.append(input_path)
         elif mode == "batch" and os.path.isdir(input_path):
             self._log_message_gui(f"🔍 Scanning directory (incl. subfolders): {input_path}")
             recursive = True
             for ext_pattern in SUPPORTED_EXTENSIONS:
                 pattern = os.path.join(input_path, "**", ext_pattern)
                 try:
                     matched = glob.glob(pattern, recursive=recursive)
                     files_to_scan.extend([f for f in matched if os.path.isfile(f)])
                 except Exception as e:
                     self._log_message_gui(f"   ❌ Error scanning for {ext_pattern}: {e}")
             files_to_scan = sorted(list(set(files_to_scan))) # Unique and sorted
             self._log_message_gui(f"   Found {len(files_to_scan)} potential files.")

         # Populate Treeview
         for f_path in files_to_scan:
             filename = os.path.basename(f_path)
             _, ext = os.path.splitext(filename.lower())
             file_type = "Video" if any(ext == ve[1:] for ve in VIDEO_EXTENSIONS) else "Audio"
             # Insert into Treeview and store the ID
             tree_id = self.file_tree.insert("", tk.END, values=(filename, file_type, STATUS_PENDING, "0.0%"))
             # Store file data associated with the Treeview item ID
             self.file_data[f_path] = {'status': STATUS_PENDING, 'type': file_type, 'tree_id': tree_id, 'duration': 0}

         self.total_batch_files = len(files_to_scan) # Update total count for ETA label


    def update_progress_labels(self, file_elapsed=None, batch_eta=None):
        """Updates the text labels next to progress bars (thread-safe)."""
        def _update():
            if file_elapsed is not None: self.file_progress_label.config(text=f"File Progress (Elapsed: {format_eta(file_elapsed)})")
            else: self.file_progress_label.config(text="File Progress:")
            is_batch = self.input_mode.get() == "batch"
            if is_batch:
                if batch_eta is not None:
                    eta_str = format_eta(batch_eta) if batch_eta >= 0 else "Calculating..."
                    self.batch_progress_label.config(text=f"Batch Progress ({self.processed_batch_files}/{self.total_batch_files}) ETA: {eta_str}")
                else:
                    count_str = f"({self.processed_batch_files}/{self.total_batch_files})" if self.total_batch_files > 0 else ""
                    self.batch_progress_label.config(text=f"Batch Progress {count_str}")
        if self.master.winfo_exists(): self.master.after(0, _update)

    def update_progress_bars(self, file_progress=None, batch_progress=None):
        """Updates the progress bar values (thread-safe)."""
        def _update():
            if file_progress is not None: self.file_progress_bar['value'] = file_progress
            if batch_progress is not None and self.input_mode.get() == "batch": self.batch_progress_bar['value'] = batch_progress
        if self.master.winfo_exists(): self.master.after(0, _update)

    def update_elapsed_time_label(self):
        """Periodically updates the file elapsed time label during processing."""
        if self.processing_active and self.file_start_time is not None:
            elapsed = time.time() - self.file_start_time
            self.update_progress_labels(file_elapsed=elapsed)
            self.master.after(1000, self.update_elapsed_time_label)

    def set_controls_state(self, state):
        """Sets the state (tk.NORMAL or tk.DISABLED) for input controls."""
        is_disabled = (state == tk.DISABLED)
        self.processing_active = is_disabled

        def _update():
            widgets_to_toggle = [ # Simplified list
                self.input_entry.master.children['!radiobutton'], self.input_entry.master.children['!radiobutton2'],
                self.input_entry, self.input_entry.master.children['!button'],
                self.model_combo, self.quant_combo, self.device_combo, self.compute_combo,
                self.beam_spinbox, self.vad_check,
                self.overwrite_check # *** Add overwrite check to toggle list ***
            ]
            for widget in widgets_to_toggle:
                 try:
                     if isinstance(widget, ttk.Combobox) and widget['state'] == 'readonly': widget.config(state='readonly')
                     elif isinstance(widget, ttk.Spinbox): widget.config(state='readonly' if is_disabled else tk.NORMAL)
                     else: widget.config(state=state)
                 except tk.TclError: pass

            if is_disabled:
                self.start_stop_button.config(text="🛑 Stop Processing", style="Stop.TButton", command=self.request_stop)
                ToolTip(self.start_stop_button, self.status_bar, "Request to stop processing.")
            else:
                self.start_stop_button.config(text="🚀 Start Transcription", style="Accent.TButton", command=self.toggle_processing)
                ToolTip(self.start_stop_button, self.status_bar, "Start processing the selected file or directory.")
                self.stop_requested = 0; self.file_start_time = None

        if self.master.winfo_exists(): self.master.after(0, _update)

    def toggle_processing(self):
        """Starts or requests to stop the transcription."""
        if not self.processing_active: self.start_transcription_thread()
        else: self.request_stop()

    def request_stop(self):
        """Handles clicks on the Stop button, managing stop levels."""
        if not self.processing_active: return
        if self.stop_requested == 0:
            if messagebox.askyesno("Confirm Stop", "Stop processing after the current file finishes?\n\n(Press Stop again or close window to force immediate stop)", icon='warning', parent=self.master):
                self.stop_requested = 1; self._log_message_gui("ℹ️ Stop requested. Will halt after current file.")
        elif self.stop_requested == 1:
            if messagebox.askyesno("Confirm Immediate Stop", "Force stop processing immediately?\n\n(Current file transcription may be incomplete/lost)", icon='error', parent=self.master):
                self.stop_requested = 2; self._log_message_gui("⚠️ IMMEDIATE STOP REQUESTED! Halting...")

    def on_closing(self):
        """Handles the window close (X) button event."""
        if self.processing_active:
            if self.stop_requested < 2:
                 if messagebox.askyesno("Confirm Exit", "Processing is active. Stop immediately and exit?\n\n(Current file transcription may be incomplete/lost)", icon='error', parent=self.master):
                     self.stop_requested = 2; self._log_message_gui("⚠️ IMMEDIATE STOP REQUESTED VIA WINDOW CLOSE!")
                     self.master.after(100, self.master.destroy)
                 else: return # Don't close
            else: self.master.destroy() # Immediate stop already requested
        else:
            if self.fig: plt.close(self.fig) # Clean up plot figure
            self.master.destroy()

    def start_transcription_thread(self):
        """Validates inputs, prepares file list, and starts the processing thread."""
        if self.processing_active: return
        input_path = self.input_path.get()
        if not input_path: messagebox.showerror("Input Error", "Please select input."); return
        if not os.path.exists(input_path): messagebox.showerror("Input Error", f"Input path does not exist:\n{input_path}"); return
        mode = self.input_mode.get()
        if mode == "single" and not os.path.isfile(input_path): messagebox.showerror("Input Error", f"Input path is not a file:\n{input_path}"); return
        if mode == "batch" and not os.path.isdir(input_path): messagebox.showerror("Input Error", f"Input path is not a directory:\n{input_path}"); return

        # --- Use files already populated in the Treeview/file_data ---
        # Repopulate list if needed (e.g., path entered manually)
        if not self.file_data or self.input_path.get() != self.file_data.get(list(self.file_data.keys())[0] if self.file_data else '', {}).get('base_dir', None): # Basic check if path changed
             self.populate_file_list()

        files_to_process = list(self.file_data.keys())
        if not files_to_process:
            messagebox.showwarning("No Files", "No supported files found in the specified path to process.")
            return

        # --- Reset state, Disable Controls, Start Thread ---
        self.stop_requested = 0; self.completed_file_times = []
        self.total_batch_files = len(files_to_process); self.processed_batch_files = 0
        self.set_controls_state(tk.DISABLED)
        # Status log cleared implicitly by replacing it with treeview
        self.update_progress_bars(file_progress=0, batch_progress=0)
        self.update_progress_labels() # Reset labels

        self._log_message_gui(f"🚀 Starting transcription for {self.total_batch_files} file(s)...")
        self.processing_thread = threading.Thread(target=self.run_transcription, args=(files_to_process,), daemon=True)
        self.processing_thread.start()
        self.update_elapsed_time_label() # Start elapsed timer updates

    def run_transcription(self, files_to_process):
        """The core transcription logic executed in the background thread."""
        model = None; is_batch = self.total_batch_files > 1
        self.batch_start_time = time.time()
        current_file_duration = 0

        try:
            model_size = self.model_size.get(); quant_suffix = self.quantization.get()
            full_model_name = f"{model_size}-{quant_suffix}" if quant_suffix else model_size
            device = self.device.get(); compute_type = self.compute_type.get()
            lang = None; task = "transcribe"
            vad = self.vad_filter.get(); beam = self.beam_size.get()
            prompt = None; need_word_timestamps = True
            overwrite = self.overwrite_output.get() # *** Get overwrite setting ***

            # --- Load Model ---
            if self.stop_requested == 2: raise InterruptedError("Stop requested before model load.")
            self._log_message_gui(f"🧠 Loading model '{full_model_name}' ({device}, {compute_type})...")
            self._log_message_gui(f"   (Will download to '{MODEL_DOWNLOAD_DIR}' if needed)")
            try:
                model = WhisperModel(full_model_name, device=device, compute_type=compute_type, download_root=MODEL_DOWNLOAD_DIR)
                self._log_message_gui("✅ Model loaded.")
            except Exception as load_e:
                 self._log_message_gui(f"❌ Error loading model: {load_e}")
                 if self.master.winfo_exists(): self.master.after(0, lambda: messagebox.showerror("Model Load Error", f"Could not load/download model '{full_model_name}'.\nError: {load_e}\nCheck path: {MODEL_DOWNLOAD_DIR}"))
                 return

            # --- Process Files Loop ---
            for i, file_path in enumerate(files_to_process):
                base_filename = os.path.basename(file_path)
                if file_path not in self.file_data: self._log_message_gui(f"⚠️ File path {file_path} not in internal list, skipping."); continue
                tree_id = self.file_data[file_path]['tree_id']

                # --- Check for Stop Request ---
                if self.stop_requested == 2: raise InterruptedError("Immediate stop requested.")
                if self.stop_requested == 1 and i > 0: self._log_message_gui("ℹ️ Stop requested after file. Halting."); break

                self.processed_batch_files = i + 1
                self.update_progress_bars(file_progress=0)
                output_base = os.path.splitext(file_path)[0]
                _, file_ext = os.path.splitext(base_filename.lower())

                # --- Determine Output Format & Check Skip (conditional) ---
                is_audio = any(file_ext == ext[1:] for ext in AUDIO_EXTENSIONS)
                is_video = any(file_ext == ext[1:] for ext in VIDEO_EXTENSIONS)
                target_timed_format = ""; save_func = None; target_ext = ""
                if is_video: target_timed_format = "SRT"; save_func = segments_to_srt; target_ext = ".srt"
                elif is_audio: target_timed_format = "LRC"; save_func = segments_to_lrc; target_ext = ".lrc"
                else: self.update_status_threadsafe(f"{STATUS_ERROR} Skipping unknown file type: {file_path}"); continue

                expected_output_path = output_base + target_ext
                # *** Conditional Skip Logic ***
                if not overwrite and os.path.exists(expected_output_path):
                    self.update_status_threadsafe(f"{STATUS_SKIPPED} Output Exists: {file_path}")
                    self.update_progress_bars(file_progress=100)
                    if is_batch: self.completed_file_times.append(0.0)
                    batch_eta_seconds = -1
                    if is_batch and self.completed_file_times:
                         valid_times = [t for t in self.completed_file_times if t >= 0]
                         if valid_times: avg_time = sum(valid_times) / len(valid_times); files_remaining = self.total_batch_files - self.processed_batch_files; batch_eta_seconds = avg_time * files_remaining
                    self.update_progress_labels(batch_eta=batch_eta_seconds)
                    current_batch_progress = (self.processed_batch_files / self.total_batch_files * 100)
                    self.update_progress_bars(batch_progress=current_batch_progress)
                    continue

                # --- If not skipped, proceed ---
                if is_batch or i == 0: self.plot_spectrogram(file_path)

                self.update_status_threadsafe(f"{STATUS_PROCESSING} {file_path}")
                self.file_start_time = time.time()
                current_file_duration = 0

                transcribe_options = dict(task=task, language=lang, vad_filter=vad, word_timestamps=need_word_timestamps, beam_size=beam, initial_prompt=prompt)
                # self._log_message_gui(f"   Options: task={task}, lang=auto, VAD={vad}, word_ts=True, beam={beam}")

                segment_list = []; file_proc_time = -1
                try:
                    if self.stop_requested == 2: raise InterruptedError("Stop requested before transcribe.")
                    segments, info = model.transcribe(file_path, **transcribe_options)
                    current_file_duration = info.duration if info else 0
                    if file_path in self.file_data: self.file_data[file_path]['duration'] = current_file_duration

                    for segment in segments:
                        if self.stop_requested == 2: raise InterruptedError("Immediate stop requested during transcription.")
                        segment_list.append(segment)
                        if current_file_duration > 0:
                            progress_percent = (segment.end / current_file_duration) * 100
                            self.update_progress_bars(file_progress=progress_percent)
                            if self.master.winfo_exists(): self.master.after(0, lambda time=segment.end: self.update_spectrogram_line(time))
                            if self.master.winfo_exists(): self.master.after(0, lambda id=tree_id, p=progress_percent: self._update_treeview_progress(id, p))

                    if self.stop_requested == 2: raise InterruptedError("Stop requested after transcription.")
                    file_proc_time = time.time() - self.file_start_time
                    if file_proc_time > 0: self.completed_file_times.append(file_proc_time)
                    detected_lang = getattr(info, 'language', 'N/A'); lang_prob = getattr(info, 'language_probability', 0.0)
                    audio_duration = getattr(info, 'duration', 0.0)
                    speedup = audio_duration / file_proc_time if file_proc_time > 0 and audio_duration > 0 else float('inf')
                    self._log_message_gui(f"   Summary for {base_filename}: Lang={detected_lang}({lang_prob:.2f}), Dur={format_eta(audio_duration)}, Time={format_eta(file_proc_time)}, Speedup={speedup:.2f}x")

                except InterruptedError as ie:
                     self.update_status_threadsafe(f"{STATUS_ERROR} Transcription interrupted: {file_path}")
                     self.file_start_time = None; self.update_progress_labels(file_elapsed=None)
                     self.hide_spectrogram_line(); break
                except Exception as file_e:
                    self.update_status_threadsafe(f"{STATUS_ERROR} Error during transcription: {file_path}")
                    self._log_message_gui(f"   Error details: {file_e}")
                    import traceback; self._log_message_gui(f"   Traceback:\n{traceback.format_exc()}")
                    file_proc_time = -1; self.hide_spectrogram_line()

                self.file_start_time = None; self.hide_spectrogram_line()

                # --- Save Outputs ---
                save_successful = False
                if not segment_list: self.update_status_threadsafe(f"{STATUS_SKIPPED} No segments generated: {file_path}")
                elif self.stop_requested < 2:
                    def save_output(fmt, path, content_func, segments):
                        out_path = f"{path}.{fmt.lower()}"
                        try:
                            content = content_func(segments)
                            with open(out_path, "w", encoding="utf-8") as f: f.write(content)
                            self._log_message_gui(f"   💾 Saved {fmt}: {os.path.basename(out_path)}")
                            return True
                        except Exception as write_e:
                            self._log_message_gui(f"   ❌ Error saving {fmt} for {base_filename}: {write_e}")
                            self.update_status_threadsafe(f"{STATUS_ERROR} Error saving {fmt}: {file_path}")
                            return False

                    txt_saved = save_output("TXT", output_base, segments_to_txt, segment_list)
                    timed_saved = False
                    if save_func: timed_saved = save_output(target_timed_format, output_base, save_func, segment_list)
                    if txt_saved and timed_saved: self.update_status_threadsafe(f"{STATUS_COMPLETED} {file_path}"); save_successful = True
                    elif not txt_saved and not timed_saved: self._log_message_gui(f"   ⚠️ Failed to save any output files for {base_filename}.")

                # --- Update Progress & ETA ---
                self.update_progress_bars(file_progress=100 if save_successful else self.file_progress_bar['value'])
                batch_eta_seconds = -1
                if is_batch:
                    current_batch_progress = (self.processed_batch_files / self.total_batch_files * 100)
                    self.update_progress_bars(batch_progress=current_batch_progress)
                    if self.completed_file_times:
                        valid_times = [t for t in self.completed_file_times if t >= 0]
                        if valid_times:
                            avg_time = sum(valid_times) / len(valid_times)
                            files_remaining = self.total_batch_files - self.processed_batch_files
                            batch_eta_seconds = avg_time * files_remaining
                    self.update_progress_labels(batch_eta=batch_eta_seconds)

            # --- End of Loop ---
            if self.stop_requested == 0:
                 self._log_message_gui("\n✅ Processing complete.")
                 if self.master.winfo_exists(): self.master.after(0, lambda: messagebox.showinfo("Success", f"Transcription finished for {self.processed_batch_files} file(s)!"))
            elif self.stop_requested == 1:
                 self._log_message_gui("\n🛑 Processing stopped after file.")
                 if self.master.winfo_exists(): self.master.after(0, lambda: messagebox.showinfo("Stopped", f"Processing stopped after completing {self.processed_batch_files} file(s)."))
            else: # stop_requested == 2
                 self._log_message_gui("\n🛑 Processing stopped immediately.")
                 completed_count = max(0, self.processed_batch_files - 1)
                 if self.master.winfo_exists(): self.master.after(0, lambda c=completed_count: messagebox.showwarning("Stopped Immediately", f"Processing stopped immediately.\n{c} file(s) completed fully."))

        except InterruptedError as ie:
             self._log_message_gui(f"\n🛑 Processing interrupted immediately.")
             completed_count = max(0, self.processed_batch_files - 1)
             if self.master.winfo_exists(): self.master.after(0, lambda c=completed_count: messagebox.showwarning("Stopped Immediately", f"Processing stopped immediately.\n{c} file(s) completed fully."))
        except Exception as e:
            error_msg = f"❌ Unexpected error: {e}"
            self._log_message_gui(error_msg)
            import traceback; self._log_message_gui(f"Traceback:\n{traceback.format_exc()}")
            if self.master.winfo_exists(): self.master.after(0, lambda e=e: messagebox.showerror("Runtime Error", f"An unexpected error occurred:\n{e}"))
            if self.processing_active and self.processed_batch_files > 0 and self.processed_batch_files <= len(files_to_process):
                 current_file_path = files_to_process[self.processed_batch_files - 1]
                 self.update_status_threadsafe(f"{STATUS_ERROR} Unexpected Error: {current_file_path}")
        finally:
            # --- Final Cleanup ---
            self.file_start_time = None; self.processing_thread = None
            self.hide_spectrogram_line()
            if self.master.winfo_exists():
                self.master.after(0, lambda: self.set_controls_state(tk.NORMAL))
                self.master.after(0, self.update_compute_types)
                self.master.after(0, lambda: self.update_progress_bars(file_progress=0, batch_progress=0))
                self.master.after(0, lambda: self.update_progress_labels())
            if model is not None:
                try:
                    import gc; del model; gc.collect()
                    if self.device.get() == 'cuda': import torch; torch.cuda.empty_cache(); self._log_message_gui("🧹 CUDA cache cleared.")
                    else: self._log_message_gui("🧹 Model resources released.")
                except Exception as clean_e: self._log_message_gui(f"   Error during cleanup: {clean_e}")

    # --- Menu Commands ---
    # (Menu command functions remain the same)
    def run_install_core_deps_thread(self):
        install_thread = threading.Thread(target=self.install_core_dependencies, daemon=True); install_thread.start()
    def install_core_dependencies(self):
        libs = ["faster-whisper", "librosa", "numpy", "matplotlib", "tkinterdnd2-universal"]
        self._log_message_gui(f"⚙️ Attempting to install/update: {', '.join(libs)}...")
        try:
            python_exe = sys.executable; command = [python_exe, "-m", "pip", "install", "--upgrade"] + libs
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')
            stdout, stderr = process.communicate()
            if stdout: self._log_message_gui("--- Install Output ---\n" + stdout + "\n--- End Output ---")
            if stderr:
                 if process.returncode != 0: self._log_message_gui("--- Install Errors ---\n" + stderr + "\n--- End Errors ---"); self.master.after(0, lambda: messagebox.showerror("Installation Error", "Failed. Check Console Log."))
                 else: self._log_message_gui("--- Install Warnings ---\n" + stderr + "\n--- End Warnings ---")
            if process.returncode == 0: self._log_message_gui("✅ Core dependencies install/update successful!"); self.master.after(0, lambda: messagebox.showinfo("Success", "Dependencies installed/updated!\nRestart may be needed."))
            else: self._log_message_gui("❌ Core dependencies installation failed.")
        except FileNotFoundError: self._log_message_gui("❌ Error: Python/pip not found."); self.master.after(0, lambda: messagebox.showerror("Error", "Python/pip not found."))
        except Exception as e: self._log_message_gui(f"❌ Install error: {e}"); self.master.after(0, lambda e=e: messagebox.showerror("Error", f"Install error: {e}"))
    def check_pytorch_install(self):
        status_message = "--- PyTorch & CUDA Status ---\n\n"; pytorch_install_command = "Visit: https://pytorch.org/get-started/locally/"
        if PYTORCH_AVAILABLE:
            status_message += f"✅ PyTorch installed (Version: {torch.__version__})\n"
            if CUDA_AVAILABLE:
                try: gpu_name = torch.cuda.get_device_name(0); status_message += f"✅ CUDA available! (GPU: {gpu_name})\n   GPU acceleration should work."
                except Exception as e: status_message += f"⚠️ CUDA detected, but failed get name: {e}\n   GPU acceleration might work."
            else: status_message += f"❌ CUDA NOT available for PyTorch.\n   GPU acceleration will NOT work.\n\nInstall PyTorch with CUDA from:\n{pytorch_install_command}\n(Select correct CUDA version)"
        else: status_message += f"❌ PyTorch NOT installed.\n   GPU requires PyTorch.\n\nInstall PyTorch (CPU or GPU) from:\n{pytorch_install_command}\n(Choose options for your system)"
        if not CUDA_AVAILABLE or not PYTORCH_AVAILABLE:
             if messagebox.askyesno("PyTorch Status", status_message + "\n\nOpen PyTorch website now?", parent=self.master): webbrowser.open(pytorch_install_command)
        else: messagebox.showinfo("PyTorch Status", status_message, parent=self.master)
    def open_model_folder(self):
        try:
            os.makedirs(MODEL_DOWNLOAD_DIR, exist_ok=True)
            if sys.platform == "win32": os.startfile(MODEL_DOWNLOAD_DIR)
            elif sys.platform == "darwin": subprocess.Popen(["open", MODEL_DOWNLOAD_DIR])
            else: subprocess.Popen(["xdg-open", MODEL_DOWNLOAD_DIR])
            self._log_message_gui(f"ℹ️ Opened model folder: {MODEL_DOWNLOAD_DIR}")
        except Exception as e: self._log_message_gui(f"❌ Failed to open model folder: {e}"); messagebox.showerror("Error", f"Could not open model folder:\n{e}")


# --- Main Execution ---
if __name__ == "__main__":
    root = None
    try:
        try: from tkinterdnd2 import TkinterDnD
        except ImportError: raise ImportError("TkinterDnD2 library not found. Please install it: pip install tkinterdnd2-universal")
        root = TkinterDnD.Tk()
        gui = WhisperGUI(root)
        root.mainloop()
    except Exception as main_e:
        import traceback; print(f"FATAL ERROR: {main_e}\n{traceback.format_exc()}")
        try:
            if root and root.winfo_exists(): root.destroy()
            error_root = tk.Tk(); error_root.withdraw()
            dep_msg = ""
            try: from tkinterdnd2 import TkinterDnD
            except ImportError: dep_msg += "- tkinterdnd2 (Run: pip install tkinterdnd2-universal)\n"
            try: import librosa
            except ImportError: dep_msg += "- librosa, numpy, matplotlib (Run: pip install librosa numpy matplotlib)\n"
            try: import faster_whisper
            except ImportError: dep_msg += "- faster-whisper (Run: pip install faster-whisper)\n"
            try: import torch; torch.cuda.is_available()
            except ImportError: dep_msg += "- PyTorch (Optional, for GPU: See PyTorch website for CUDA install)\n"
            except Exception: dep_msg += "- PyTorch+CUDA (Optional, GPU detection failed - check drivers/install)\n"
            full_msg = f"Could not start GUI.\nError: {main_e}\n"
            if dep_msg: full_msg += f"\nCheck dependencies:\n{dep_msg}"
            full_msg += "\nSee console for details."
            messagebox.showerror("Fatal GUI Error", full_msg, parent=None)
            error_root.destroy()
        except Exception as fallback_e: print(f"Fallback error display failed: {fallback_e}")
