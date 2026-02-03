# -*- coding: utf-8 -*-
"""
Audio Cleaner GUI for DrumBin.
Integrates functionality of clean_to_wav_configured.sh without ffmpeg dependency.
"""

import os
import time
import traceback
import numpy as np
import soundfile as sf
from typing import List, Tuple, Optional

from PySide6.QtCore import Qt, QThread, Signal, QObject
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QLineEdit,
    QCheckBox, QComboBox, QFileDialog, QProgressBar, QTextEdit, QGroupBox,
    QListWidget, QAbstractItemView, QSpinBox, QMessageBox, QGridLayout
)

# Supported extensions from the original script
DEFAULT_EXTS = {"wav", "mp3", "flac", "aif", "aiff", "m4a", "ogg", "opus", "wma", "aac", "caf", "aiffc"}


def resample_linear(data: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
    """
    Simple linear interpolation resampling using numpy.
    """
    if orig_sr == target_sr:
        return data

    old_len = len(data)
    duration = old_len / orig_sr
    new_len = int(duration * target_sr)

    x_old = np.linspace(0, old_len - 1, old_len)
    x_new = np.linspace(0, old_len - 1, new_len)

    if data.ndim == 1:
        return np.interp(x_new, x_old, data).astype(data.dtype)
    else:
        # Multichannel
        channels = data.shape[1]
        out = np.zeros((new_len, channels), dtype=data.dtype)
        for i in range(channels):
            out[:, i] = np.interp(x_new, x_old, data[:, i])
        return out


class CleanerWorker(QThread):
    progress_signal = Signal(int, int, str)  # current, total, message
    log_signal = Signal(str)
    finished_signal = Signal(dict)  # summary report

    def __init__(self, file_list: List[Tuple[str, str]], output_dir: str, 
                 target_sr: int, channels: str, suffix: str, exts: set):
        super().__init__()
        self.file_list = file_list
        self.output_dir = output_dir
        self.target_sr = target_sr
        self.channels_mode = channels  # "1", "2", "Keep"
        self.suffix = suffix
        self.exts = exts
        self._is_running = True

    def run(self):
        total = len(self.file_list)
        success_count = 0
        fail_count = 0
        skipped_count = 0
        
        self.log_signal.emit(f"Starting processing of {total} files...")
        self.log_signal.emit(f"Target: {self.target_sr}Hz, Channels: {self.channels_mode}, Suffix: '{self.suffix}'")

        for idx, (src_path, rel_base) in enumerate(self.file_list):
            if not self._is_running:
                break
            
            try:
                # Check extension
                ext = os.path.splitext(src_path)[1].lower().lstrip('.')
                if ext not in self.exts:
                    self.log_signal.emit(f"[SKIP] {src_path} (Excluded extension)")
                    skipped_count += 1
                    self.progress_signal.emit(idx + 1, total, f"Skipping {os.path.basename(src_path)}")
                    continue

                # Calculate dest path
                # rel_base is the root directory this file belongs to (for structure mirroring)
                # If rel_base is None, we put it in root of output
                if rel_base:
                    try:
                        rel_path = os.path.relpath(src_path, rel_base)
                    except ValueError:
                        # Fallback if paths are on different drives
                        rel_path = os.path.basename(src_path)
                else:
                    rel_path = os.path.basename(src_path)

                dest_dir = os.path.dirname(os.path.join(self.output_dir, rel_path))
                basename = os.path.splitext(os.path.basename(src_path))[0]
                dest_filename = f"{basename}{self.suffix}.wav"
                dest_path = os.path.join(dest_dir, dest_filename)

                os.makedirs(dest_dir, exist_ok=True)

                self.progress_signal.emit(idx + 1, total, f"Processing {os.path.basename(src_path)}")

                # Process audio
                # Read
                try:
                    data, sr = sf.read(src_path)
                except Exception as e:
                    self.log_signal.emit(f"[ERROR] Failed to read {src_path}: {e}")
                    fail_count += 1
                    continue

                # Check dimensions
                if data.ndim == 1:
                    # Mono to (N, 1) for uniform handling if needed, or keep 1D
                    pass 
                
                # Resample if needed
                if sr != self.target_sr:
                    data = resample_linear(data, sr, self.target_sr)

                # Channel conversion
                if self.channels_mode == "1":
                    if data.ndim > 1:
                        # Average channels to mono
                        data = np.mean(data, axis=1)
                elif self.channels_mode == "2":
                    if data.ndim == 1:
                        # Mono to Stereo
                        data = np.column_stack((data, data))
                    elif data.shape[1] > 2:
                        # Downmix first 2? Or just take first 2
                        data = data[:, :2]
                
                # Normalize / Clip to avoid wrapping?
                # The script does generic ffmpeg conversion. 
                # Converting to int16 requires clipping.
                if data.dtype.kind == 'f':
                    data = np.clip(data, -1.0, 1.0)
                
                # Write to WAV (16-bit PCM default per script)
                # Script: -acodec pcm_s16le
                sf.write(dest_path, data, self.target_sr, subtype='PCM_16')
                
                self.log_signal.emit(f"[OK] {src_path} -> {dest_path}")
                success_count += 1

            except Exception as e:
                self.log_signal.emit(f"[FAIL] {src_path}: {traceback.format_exc()}")
                fail_count += 1

        self.finished_signal.emit({
            "total": total,
            "success": success_count,
            "fail": fail_count,
            "skipped": skipped_count
        })

    def stop(self):
        self._is_running = False


class CleanerWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.files = []  # List[Tuple[full_path, root_path]]
        self.worker = None

        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)

        # Top Control Bar
        top_layout = QHBoxLayout()
        
        self.btn_add_folder = QPushButton("Add Folder (Recursive)")
        self.btn_add_folder.clicked.connect(self.add_folder)
        self.btn_clear = QPushButton("Clear List")
        self.btn_clear.clicked.connect(self.clear_list)
        
        top_layout.addWidget(self.btn_add_folder)
        top_layout.addWidget(self.btn_clear)
        top_layout.addStretch()
        
        layout.addLayout(top_layout)

        # File List Area
        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list_widget.setAcceptDrops(True)
        self.list_widget.dragEnterEvent = self.dragEnterEvent
        self.list_widget.dragMoveEvent = self.dragMoveEvent
        self.list_widget.dropEvent = self.dropEvent
        layout.addWidget(QLabel("Input Files (Drag & Drop supported):"))
        layout.addWidget(self.list_widget)

        # Settings Group
        settings_group = QGroupBox("Configuration")
        settings_layout = QGridLayout()
        
        # Output Dir
        settings_layout.addWidget(QLabel("Output Directory:"), 0, 0)
        self.edit_out_dir = QLineEdit()
        self.btn_browse_out = QPushButton("Browse...")
        self.btn_browse_out.clicked.connect(self.browse_output)
        settings_layout.addWidget(self.edit_out_dir, 0, 1)
        settings_layout.addWidget(self.btn_browse_out, 0, 2)

        # Suffix
        settings_layout.addWidget(QLabel("Filename Suffix:"), 1, 0)
        self.edit_suffix = QLineEdit("_22050_16bit")
        settings_layout.addWidget(self.edit_suffix, 1, 1)

        # Sample Rate
        settings_layout.addWidget(QLabel("Sample Rate:"), 2, 0)
        self.combo_sr = QComboBox()
        self.combo_sr.addItems(["22050", "44100", "48000", "16000", "8000"])
        settings_layout.addWidget(self.combo_sr, 2, 1)

        # Channels
        settings_layout.addWidget(QLabel("Channels:"), 3, 0)
        self.combo_ch = QComboBox()
        self.combo_ch.addItems(["Mono (1)", "Stereo (2)", "Keep Original"])
        settings_layout.addWidget(self.combo_ch, 3, 1)

        settings_group.setLayout(settings_layout)
        layout.addWidget(settings_group)

        # Progress & Log
        self.progress_bar = QProgressBar()
        layout.addWidget(self.progress_bar)
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(150)
        layout.addWidget(self.log_text)

        # Action Buttons
        btn_layout = QHBoxLayout()
        self.btn_start = QPushButton("Start Processing")
        self.btn_start.clicked.connect(self.start_processing)
        self.btn_start.setFixedHeight(40)
        self.btn_start.setStyleSheet("font-weight: bold; font-size: 14px;")
        
        self.btn_stop = QPushButton("Stop")
        self.btn_stop.clicked.connect(self.stop_processing)
        self.btn_stop.setEnabled(False)

        btn_layout.addWidget(self.btn_start)
        btn_layout.addWidget(self.btn_stop)
        layout.addLayout(btn_layout)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        event.acceptProposedAction()

    def dropEvent(self, event):
        paths = []
        for url in event.mimeData().urls():
            paths.append(url.toLocalFile())
        self.add_paths(paths)

    def add_paths(self, paths):
        for p in paths:
            if os.path.isdir(p):
                self.scan_directory(p, p)
            else:
                if self.is_supported(p):
                    self.add_file_item(p, os.path.dirname(p))

    def add_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Select Folder")
        if d:
            self.scan_directory(d, d)

    def scan_directory(self, root_path, base_path):
        for root, dirs, files in os.walk(root_path):
            for f in files:
                full_path = os.path.join(root, f)
                if self.is_supported(full_path):
                    self.add_file_item(full_path, base_path)

    def is_supported(self, path):
        ext = os.path.splitext(path)[1].lower().lstrip('.')
        return ext in DEFAULT_EXTS

    def add_file_item(self, path, root):
        # Avoid duplicates
        # O(N) check is fine for small lists, but for thousands might be slow. 
        # For now assume user doesn't drag 10k files at once.
        if any(f[0] == path for f in self.files):
            return
        self.files.append((path, root))
        self.list_widget.addItem(f"{os.path.basename(path)}  ({os.path.dirname(path)})")

    def clear_list(self):
        self.files.clear()
        self.list_widget.clear()

    def browse_output(self):
        d = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if d:
            self.edit_out_dir.setText(d)

    def start_processing(self):
        out_dir = self.edit_out_dir.text().strip()
        if not out_dir:
            QMessageBox.warning(self, "Error", "Please select an output directory.")
            return
        
        if not self.files:
            QMessageBox.warning(self, "Error", "No files to process.")
            return

        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.log_text.clear()
        self.progress_bar.setValue(0)

        target_sr = int(self.combo_sr.currentText())
        
        ch_text = self.combo_ch.currentText()
        if "Mono" in ch_text:
            ch = "1"
        elif "Stereo" in ch_text:
            ch = "2"
        else:
            ch = "Keep"

        suffix = self.edit_suffix.text()

        self.worker = CleanerWorker(
            self.files, out_dir, target_sr, ch, suffix, DEFAULT_EXTS
        )
        self.worker.progress_signal.connect(self.update_progress)
        self.worker.log_signal.connect(self.append_log)
        self.worker.finished_signal.connect(self.processing_finished)
        self.worker.start()

    def stop_processing(self):
        if self.worker:
            self.worker.stop()
            self.append_log("Stopping...")

    def update_progress(self, current, total, msg):
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)
        # Optional: show msg in status bar or log?
        # self.append_log(msg) 

    def append_log(self, text):
        self.log_text.append(text)

    def processing_finished(self, summary):
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        QMessageBox.information(
            self, "Finished", 
            f"Processing Complete!\n\n"
            f"Total: {summary['total']}\n"
            f"Success: {summary['success']}\n"
            f"Failed: {summary['fail']}\n"
            f"Skipped: {summary['skipped']}"
        )


