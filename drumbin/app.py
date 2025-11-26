#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Multi Tool App (Two Pages)
1) WAV → BIN (Offsets) : drag & drop WAVs, compute aligned offsets, export BIN/CSV/JSON, copy offsets
2) MIDI PPQN Converter  : drag & drop MIDIs, set target PPQN, batch convert (+ optional unsigned char hex array .h)
Dependencies: PySide6, mido
"""

import sys, os, json, csv, re
from typing import List, Tuple, Optional

from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QPushButton, QTableWidget, QTableWidgetItem,
    QFileDialog, QMessageBox, QLabel, QHBoxLayout, QAbstractItemView, QSpinBox, QCheckBox,
    QLineEdit, QTabWidget, QMainWindow
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QDesktopServices
from PySide6.QtCore import QUrl

# ---- Common helpers for WAV page ----

def read_file_size(path: str) -> int:
    return os.path.getsize(path)

def is_wav(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            riff = f.read(12)
            if len(riff) < 12:
                return False
            # RIFF .... WAVE
            return riff[:4] == b"RIFF" and riff[8:12] == b"WAVE"
    except Exception:
        return False

def compute_offsets(files: List[Tuple[str, int]], align_bytes: int) -> List[int]:
    """files: list[(path,size)] -> list[offset] from BIN start with alignment between items"""
    offsets = []
    acc = 0
    for i, (_, size) in enumerate(files):
        offsets.append(acc)
        acc += size
        if align_bytes > 1 and i < len(files) - 1:
            pad = (-acc) % align_bytes
            acc += pad
    return offsets

# ---- WAV page widgets ----

class WavDropTable(QTableWidget):
    def __init__(self, parent=None):
        super().__init__(0, 4, parent)
        self.setHorizontalHeaderLabels(["Index", "Filename", "Offset (hex)", "Offset (dec)"])
        self.setAcceptDrops(True)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.files: List[Tuple[str, int]] = []  # list of (path, size)
        self.align_bytes: int = 1
        self.use_hex: bool = True
        self.resizeColumnsToContents()

    # ---- Drag & Drop ----
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        event.acceptProposedAction()

    def dropEvent(self, event):
        paths = []
        for url in event.mimeData().urls():
            p = url.toLocalFile()
            if os.path.isdir(p):
                for root, _, files in os.walk(p):
                    for fn in files:
                        paths.append(os.path.join(root, fn))
            else:
                paths.append(p)
        self.add_files(paths)

    # ---- Data ops ----
    def add_files(self, paths: List[str]):
        added = 0
        for p in paths:
            if not os.path.isfile(p) or not is_wav(p):
                continue
            try:
                size = read_file_size(p)
            except Exception as e:
                QMessageBox.warning(self, "Skip", f"Failed to read '{p}':\n{e}")
                continue
            self.files.append((p, size))
            added += 1
        if added == 0:
            QMessageBox.information(self, "Info", "No valid WAV files found.")
        self.refresh_table()

    def clear_files(self):
        self.files.clear()
        self.setRowCount(0)

    def move_up(self):
        rows = sorted({idx.row() for idx in self.selectedIndexes()})
        if not rows or rows[0] == 0:
            return
        for r in rows:
            self.files[r-1], self.files[r] = self.files[r], self.files[r-1]
        self.selectRow(rows[0]-1)
        self.refresh_table()

    def move_down(self):
        rows = sorted({idx.row() for idx in self.selectedIndexes()}, reverse=True)
        if not rows or rows[0] == len(self.files) - 1:
            return
        for r in rows:
            self.files[r+1], self.files[r] = self.files[r], self.files[r+1]
        self.selectRow(rows[0]+1)
        self.refresh_table()

    def refresh_table(self):
        offs = compute_offsets(self.files, self.align_bytes)
        self.setRowCount(len(self.files))
        for i, ((p, _), off) in enumerate(zip(self.files, offs)):
            name = os.path.basename(p)
            self.setItem(i, 0, QTableWidgetItem(str(i)))
            self.setItem(i, 1, QTableWidgetItem(name))
            self.setItem(i, 2, QTableWidgetItem(f"0x{off:08X}"))
            self.setItem(i, 3, QTableWidgetItem(str(off)))
        self.resizeColumnsToContents()

    # ---- Export & Copy ----
    def export_bin(self):
        if not self.files:
            QMessageBox.warning(self, "Warning", "No files to export.")
            return
        out, _ = QFileDialog.getSaveFileName(self, "Export BIN", "output.bin", "BIN (*.bin)")
        if not out:
            return
        try:
            offs = compute_offsets(self.files, self.align_bytes)
            with open(out, "wb") as w:
                acc = 0
                for i, (p, _) in enumerate(self.files):
                    with open(p, "rb") as r:
                        data = r.read()
                        w.write(data)
                        acc += len(data)
                    if self.align_bytes > 1 and i < len(self.files) - 1:
                        pad = (-acc) % self.align_bytes
                        if pad:
                            w.write(b"\x00" * pad)
                            acc += pad
            QMessageBox.information(self, "Success", f"BIN saved:\n{out}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Export failed:\n{e}")

    def copy_offsets_plain(self):
        offs = compute_offsets(self.files, self.align_bytes)
        if self.use_hex:
            text = ", ".join([f"0x{o:08X}" for o in offs])
        else:
            text = ", ".join([str(o) for o in offs])
        QGuiApplication.clipboard().setText(text)
        QMessageBox.information(self, "Copied", "Offsets copied to clipboard.")

    def copy_offsets_c_array(self):
        offs = compute_offsets(self.files, self.align_bytes)
        body = ", ".join([f"0x{o:08X}" if self.use_hex else str(o) for o in offs])
        array = (
            "/* Autogenerated by BinBeats - Offsets from BIN start */\n"
            "const uint32_t kOffsets[] = { " + body + " };\n"
            "const size_t kOffsetsCount = sizeof(kOffsets)/sizeof(kOffsets[0]);\n"
        )
        QGuiApplication.clipboard().setText(array)
        QMessageBox.information(self, "Copied", "C array copied to clipboard.")

    def export_csv(self):
        if not self.files:
            QMessageBox.warning(self, "Warning", "No files to export.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export CSV", "offsets.csv", "CSV (*.csv)")
        if not path:
            return
        offs = compute_offsets(self.files, self.align_bytes)
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Index", "Filename", "Offset (hex)", "Offset (dec)"])
            for i, ((p, _), off) in enumerate(zip(self.files, offs)):
                writer.writerow([i, os.path.basename(p), f"0x{off:08X}", off])
        QMessageBox.information(self, "Success", f"CSV exported:\n{path}")

    def export_json(self):
        if not self.files:
            QMessageBox.warning(self, "Warning", "No files to export.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export JSON", "offsets.json", "JSON (*.json)")
        if not path:
            return
        offs = compute_offsets(self.files, self.align_bytes)
        obj = [
            {
                "index": i,
                "filename": os.path.basename(p),
                "offset_hex": f"0x{off:08X}",
                "offset_dec": off,
            }
            for i, ((p, _), off) in enumerate(zip(self.files, offs))
        ]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        QMessageBox.information(self, "Success", f"JSON exported:\n{path}")

class BinBeatsPage(QWidget):
    def __init__(self):
        super().__init__()
        self.table = WavDropTable(self)

        # Controls
        btn_add = QPushButton("Add WAV...")
        btn_clear = QPushButton("Clear")
        btn_up = QPushButton("Move Up")
        btn_down = QPushButton("Move Down")
        btn_export = QPushButton("Export BIN")

        btn_copy_plain = QPushButton("Copy Offsets")
        btn_copy_c = QPushButton("Copy C Array")
        btn_csv = QPushButton("Export CSV")
        btn_json = QPushButton("Export JSON")

        self.align_spin = QSpinBox()
        self.align_spin.setRange(1, 1_048_576)
        self.align_spin.setValue(1)
        self.align_spin.setSingleStep(1)
        self.align_spin.setToolTip("Alignment in bytes between files in BIN")

        self.hex_check = QCheckBox("Hex in copy")

        # Wire
        btn_add.clicked.connect(self.choose_files)
        btn_clear.clicked.connect(self.table.clear_files)
        btn_up.clicked.connect(self.table.move_up)
        btn_down.clicked.connect(self.table.move_down)
        btn_export.clicked.connect(self.table.export_bin)

        btn_copy_plain.clicked.connect(self.table.copy_offsets_plain)
        btn_copy_c.clicked.connect(self.table.copy_offsets_c_array)
        btn_csv.clicked.connect(self.table.export_csv)
        btn_json.clicked.connect(self.table.export_json)

        self.align_spin.valueChanged.connect(self.on_align_changed)
        self.hex_check.stateChanged.connect(self.on_hex_changed)
        # Sync initial state
        self.on_hex_changed(self.hex_check.checkState())

        # Layout
        bar1 = QHBoxLayout()
        bar1.addWidget(btn_add)
        bar1.addWidget(btn_clear)
        bar1.addStretch()
        bar1.addWidget(btn_up)
        bar1.addWidget(btn_down)
        bar1.addWidget(btn_export)

        bar2 = QHBoxLayout()
        bar2.addWidget(QLabel("Alignment:"))
        bar2.addWidget(self.align_spin)
        bar2.addSpacing(16)
        bar2.addWidget(self.hex_check)
        bar2.addStretch()
        bar2.addWidget(btn_copy_plain)
        bar2.addWidget(btn_copy_c)
        bar2.addWidget(btn_csv)
        bar2.addWidget(btn_json)

        tips = QLabel("Tip: Drag & drop WAV files here. BIN export concatenates data with optional zero padding.")
        tips.setStyleSheet("color: gray;")

        lay = QVBoxLayout(self)
        lay.addLayout(bar1)
        lay.addLayout(bar2)
        lay.addWidget(self.table)
        lay.addWidget(tips)

    # slots
    def on_align_changed(self, v: int):
        self.table.align_bytes = int(v)
        self.table.refresh_table()

    def on_hex_changed(self, state):
        self.table.use_hex = (state == Qt.Checked)

    def choose_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Select WAV files", "", "WAV files (*.wav)")
        if files:
            self.table.add_files(files)

# ---- MIDI PPQN Converter page ----

import mido

def is_midi_file(path: str) -> bool:
    ext = os.path.splitext(path)[1].lower()
    return ext in {".mid", ".midi"}

def probe_midi(path: str) -> Tuple[Optional[int], Optional[int], Optional[str]]:
    """Return (ppqn, tracks_count, error)"""
    try:
        mid = mido.MidiFile(path)
        return mid.ticks_per_beat, len(mid.tracks), None
    except Exception as e:
        return None, None, str(e)

def suggest_output_path(src: str, ppqn: int, out_dir: Optional[str], overwrite: bool) -> str:
    base = os.path.splitext(os.path.basename(src))[0]
    folder = out_dir if out_dir else os.path.dirname(src)
    name = f"{base}_ppqn{ppqn}.mid"
    out = os.path.join(folder, name)
    if overwrite:
        return out
    # Avoid overwriting by adding (n) suffix
    candidate = out
    i = 1
    while os.path.exists(candidate):
        candidate = os.path.join(folder, f"{base}_ppqn{ppqn} ({i}).mid")
        i += 1
    return candidate

def to_c_identifier(s: str) -> str:
    s2 = re.sub(r'[^0-9a-zA-Z_]', '_', s)
    if not s2 or s2[0].isdigit():
        s2 = '_' + s2
    return s2

def export_hex_header_from_file(src: str, header_path: str, varname: str):
    """
    Write a C header containing an unsigned char array of the exact MIDI bytes in hex.
    Example style:
        unsigned char hexData[126] = { 0x4D, 0x54, ... };
    """
    with open(src, "rb") as f:
        data = f.read()

    # Format: 16 bytes per line, uppercase hex
    lines = []
    for i in range(0, len(data), 16):
        chunk = ", ".join(f"0x{b:02X}" for b in data[i:i+16])
        lines.append("    " + chunk)
    body = ",\n".join(lines) if lines else "    /* empty */"

    guard = to_c_identifier(os.path.basename(header_path)).upper() + "_INCLUDE_GUARD"
    base = to_c_identifier(varname)
    content = (
        f"#ifndef {guard}\n#define {guard}\n\n"
        f"#include <stddef.h>\n\n"
        f"/* Autogenerated: raw MIDI bytes as hex.\n"
        f" * Byte count = {len(data)}.\n"
        f" */\n"
        f"static const unsigned char {base}[{len(data)}] = {{\n{body}\n}};\n\n"
        f"static const size_t {base}_size = {len(data)};\n\n"
        f"#endif /* {guard} */\n"
    )
    with open(header_path, "w", encoding="utf-8") as w:
        w.write(content)

def convert_midi_ppqn(src: str, dst: str, new_ppqn: int) -> str:
    """
    Convert MIDI PPQN preserving musical timing by rescaling delta-times.
    Returns a status string: 'converted', 'copied', or raises on error.
    """
    mid = mido.MidiFile(src)
    old_ppqn = mid.ticks_per_beat
    if old_ppqn == new_ppqn:
        mid.save(dst)
        return "copied"

    scale = float(new_ppqn) / float(old_ppqn)

    new_mid = mido.MidiFile()
    new_mid.ticks_per_beat = new_ppqn

    for track in mid.tracks:
        new_track = mido.MidiTrack()
        new_mid.tracks.append(new_track)

        abs_old = 0
        abs_new_rounded = 0

        for msg in track:
            abs_old += msg.time
            new_abs = abs_old * scale
            new_abs_rounded = int(round(new_abs))
            delta = new_abs_rounded - abs_new_rounded
            new_track.append(msg.copy(time=delta))
            abs_new_rounded = new_abs_rounded

    new_mid.save(dst)
    return "converted"

class MidiTable(QTableWidget):
    COL_INDEX = 0
    COL_NAME = 1
    COL_PPQN = 2
    COL_TRACKS = 3
    COL_TARGET = 4
    COL_OUTPUT = 5
    COL_HEADER = 6
    COL_STATUS = 7

    def __init__(self, parent=None):
        super().__init__(0, 8, parent)
        self.setHorizontalHeaderLabels(
            ["Index", "Filename", "PPQN", "Tracks", "Target PPQN", "Output (.mid)", "Header (.h)", "Status"]
        )
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setAcceptDrops(True)

        self.items: List[dict] = []
        self.target_ppqn: int = 120
        self.out_dir: Optional[str] = None
        self.overwrite: bool = False
        self.export_hex: bool = False  # NEW: export .h with unsigned char hex array

        self.resizeColumnsToContents()

    # Drag & drop
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        event.acceptProposedAction()

    def dropEvent(self, event):
        paths = []
        for url in event.mimeData().urls():
            p = url.toLocalFile()
            if os.path.isdir(p):
                for root, _, files in os.walk(p):
                    for fn in files:
                        paths.append(os.path.join(root, fn))
            else:
                paths.append(p)
        self.add_files(paths)

    # Settings sync
    def set_target_ppqn(self, v: int):
        self.target_ppqn = int(v)
        self.refresh_table()

    def set_out_dir(self, path: Optional[str]):
        self.out_dir = path if path else None
        self.refresh_table()

    def set_overwrite(self, on: bool):
        self.overwrite = bool(on)
        self.refresh_table()

    def set_export_hex(self, on: bool):
        self.export_hex = bool(on)

    # Data ops
    def add_files(self, paths: List[str]):
        added = 0
        for p in paths:
            if not os.path.isfile(p) or not is_midi_file(p):
                continue
            ppqn, tracks, err = probe_midi(p)
            if err is not None or ppqn is None:
                QMessageBox.warning(self, "Skip", f"Failed to read '{p}':\n{err}")
                continue
            self.items.append({
                "path": p,
                "ppqn": ppqn,
                "tracks": tracks,
                "status": "",
            })
            added += 1

        if added == 0:
            QMessageBox.information(self, "Info", "No valid MIDI files found.")
        self.refresh_table()

    def clear_files(self):
        self.items.clear()
        self.setRowCount(0)

    def move_up(self):
        rows = sorted({idx.row() for idx in self.selectedIndexes()})
        if not rows or rows[0] == 0:
            return
        for r in rows:
            self.items[r-1], self.items[r] = self.items[r], self.items[r-1]
        self.selectRow(rows[0]-1)
        self.refresh_table()

    def move_down(self):
        rows = sorted({idx.row() for idx in self.selectedIndexes()}, reverse=True)
        if not rows or rows[0] == len(self.items) - 1:
            return
        for r in rows:
            self.items[r+1], self.items[r] = self.items[r], self.items[r+1]
        self.selectRow(rows[0]+1)
        self.refresh_table()

    def refresh_table(self):
        self.setRowCount(len(self.items))
        for i, item in enumerate(self.items):
            p = item["path"]
            name = os.path.basename(p)
            out_path = suggest_output_path(p, self.target_ppqn, self.out_dir, self.overwrite)

            self.setItem(i, self.COL_INDEX, QTableWidgetItem(str(i)))
            self.setItem(i, self.COL_NAME, QTableWidgetItem(name))
            self.setItem(i, self.COL_PPQN, QTableWidgetItem(str(item["ppqn"])))
            self.setItem(i, self.COL_TRACKS, QTableWidgetItem(str(item["tracks"])))
            self.setItem(i, self.COL_TARGET, QTableWidgetItem(str(self.target_ppqn)))
            self.setItem(i, self.COL_OUTPUT, QTableWidgetItem(out_path))
            self.setItem(i, self.COL_HEADER, QTableWidgetItem(item.get("header", "")))
            self.setItem(i, self.COL_STATUS, QTableWidgetItem(item.get("status", "")))

        self.resizeColumnsToContents()

    # Export
    def convert_all(self):
        if not self.items:
            QMessageBox.warning(self, "Warning", "No files to convert.")
            return

        successes = 0
        copies = 0
        errors = 0
        header_paths = []

        if self.out_dir and not os.path.isdir(self.out_dir):
            try:
                os.makedirs(self.out_dir, exist_ok=True)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Cannot create output directory:\n{self.out_dir}\n{e}")
                return

        for i, item in enumerate(self.items):
            src = item["path"]
            dst = suggest_output_path(src, self.target_ppqn, self.out_dir, self.overwrite)

            self.item(i, self.COL_STATUS).setText("Converting...")
            QApplication.processEvents()

            try:
                result = convert_midi_ppqn(src, dst, self.target_ppqn)
                header_ok = ""
                header_path = ""
                if self.export_hex:
                    try:
                        folder = os.path.dirname(dst)
                        base = os.path.splitext(os.path.basename(dst))[0]
                        varname = to_c_identifier(base + "_hex")
                        header_path = os.path.join(folder, f"{base}_hex.h")
                        export_hex_header_from_file(dst, header_path, varname)
                        item["header"] = header_path
                        header_paths.append(header_path)
                        header_ok = " +hex.h"
                    except Exception as he:
                        item["header"] = f"ERROR: {he}"
                        header_ok = f" (+hex FAILED: {he})"
                if result == "converted":
                    item["status"] = "OK" + header_ok
                    successes += 1
                elif result == "copied":
                    item["status"] = "Skipped (same PPQN → copied)" + header_ok
                    copies += 1
                else:
                    item["status"] = (result or "OK") + header_ok
                    successes += 1
            except Exception as e:
                item["status"] = f"Error: {e}"
                errors += 1

            self.setItem(i, self.COL_OUTPUT, QTableWidgetItem(dst))
            self.setItem(i, self.COL_HEADER, QTableWidgetItem(item.get("header", "")))
            self.setItem(i, self.COL_STATUS, QTableWidgetItem(item["status"]))

        self.resizeColumnsToContents()

        msg = f"Done.\nConverted: {successes}\nCopied: {copies}\nErrors: {errors}" + ("\n\nHeaders:\n" + "\n".join(header_paths) if header_paths else "")
        if errors:
            QMessageBox.warning(self, "Completed with errors", msg)
        else:
            QMessageBox.information(self, "Success", msg)

class MidiPPQNPage(QWidget):
    def __init__(self):
        super().__init__()
        self.table = MidiTable(self)

        # Controls
        btn_add = QPushButton("Add MIDI...")
        btn_clear = QPushButton("Clear")
        btn_up = QPushButton("Move Up")
        btn_down = QPushButton("Move Down")
        btn_convert = QPushButton("Convert All")
        btn_open_dir = QPushButton("Open Output Dir")
        btn_export_headers = QPushButton("Export Headers")

        self.ppqn_spin = QSpinBox()
        self.ppqn_spin.setRange(12, 9600)
        self.ppqn_spin.setValue(120)
        self.ppqn_spin.setSingleStep(1)
        self.ppqn_spin.setToolTip("Target PPQN (ticks per quarter note)")

        self.out_dir_edit = QLineEdit()
        self.out_dir_edit.setPlaceholderText("(Same as input)")
        self.out_dir_edit.setReadOnly(True)
        btn_choose_dir = QPushButton("Choose Output Dir")
        btn_clear_dir = QPushButton("Clear")
        self.overwrite_check = QCheckBox("Overwrite existing files")

        # NEW: export unsigned char hex array switch
        self.hex_check = QCheckBox("Also export unsigned char hex array header (.h)")
        self.hex_check.setChecked(True)

        # Wire
        btn_add.clicked.connect(self.choose_files)
        btn_clear.clicked.connect(self.table.clear_files)
        btn_up.clicked.connect(self.table.move_up)
        btn_down.clicked.connect(self.table.move_down)
        btn_convert.clicked.connect(self.table.convert_all)
        btn_open_dir.clicked.connect(self.open_output_dir)
        btn_export_headers.clicked.connect(self.export_headers_only)

        self.ppqn_spin.valueChanged.connect(self.on_ppqn_changed)
        btn_choose_dir.clicked.connect(self.choose_out_dir)
        btn_clear_dir.clicked.connect(self.clear_out_dir)
        self.overwrite_check.stateChanged.connect(self.on_overwrite_changed)
        self.hex_check.stateChanged.connect(self.on_hex_changed)
        # Sync initial state
        self.on_hex_changed(self.hex_check.checkState())

        # Layout
        bar1 = QHBoxLayout()
        bar1.addWidget(btn_add)
        bar1.addWidget(btn_clear)
        bar1.addStretch()
        bar1.addWidget(btn_up)
        bar1.addWidget(btn_down)
        bar1.addWidget(btn_convert)
        bar1.addWidget(btn_open_dir)
        bar1.addWidget(btn_export_headers)

        bar2 = QHBoxLayout()
        bar2.addWidget(QLabel("Target PPQN:"))
        bar2.addWidget(self.ppqn_spin)
        bar2.addSpacing(16)
        bar2.addWidget(QLabel("Output Dir:"))
        bar2.addWidget(self.out_dir_edit, 1)
        bar2.addWidget(btn_choose_dir)
        bar2.addWidget(btn_clear_dir)
        bar2.addSpacing(16)
        bar2.addWidget(self.overwrite_check)
        bar2.addSpacing(16)
        bar2.addWidget(self.hex_check)

        tips = QLabel("Tip: Drag & drop .mid/.midi files here. If enabled, a .h with unsigned char hex array is written beside the .mid output.")
        tips.setStyleSheet("color: gray;")

        lay = QVBoxLayout(self)
        lay.addLayout(bar1)
        lay.addLayout(bar2)
        lay.addWidget(self.table)
        lay.addWidget(tips)

    # slots
    def on_ppqn_changed(self, v: int):
        self.table.set_target_ppqn(int(v))

    def choose_out_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Choose Output Directory", "")
        if d:
            self.out_dir_edit.setText(d)
            self.table.set_out_dir(d)

    def clear_out_dir(self):
        self.out_dir_edit.clear()
        self.table.set_out_dir(None)

    def on_overwrite_changed(self, state):
        self.table.set_overwrite(state == Qt.Checked)

    def on_hex_changed(self, state):
        self.table.set_export_hex(state == Qt.Checked)

    def export_headers_only(self):
        # Export headers for selected rows (or all if none selected)
        rows = sorted({idx.row() for idx in self.table.selectedIndexes()})
        if not rows:
            rows = list(range(len(self.table.items)))
        if not rows:
            QMessageBox.information(self, "Info", "No items to export headers for.")
            return
        created = []
        failed = []
        for r in rows:
            item = self.table.items[r]
            # Determine dst path as shown in table
            dst = self.table.item(r, self.table.COL_OUTPUT).text()
            if not os.path.isfile(dst):
                failed.append((r, "MID not found: " + dst))
                continue
            try:
                folder = os.path.dirname(dst)
                base = os.path.splitext(os.path.basename(dst))[0]
                varname = to_c_identifier(base + "_hex")
                header_path = os.path.join(folder, f"{base}_hex.h")
                export_hex_header_from_file(dst, header_path, varname)
                item["header"] = header_path
                self.table.setItem(r, self.table.COL_HEADER, QTableWidgetItem(header_path))
                created.append(header_path)
            except Exception as e:
                item["header"] = f"ERROR: {e}"
                self.table.setItem(r, self.table.COL_HEADER, QTableWidgetItem(item["header"]))
                failed.append((r, str(e)))
        msg = []
        if created:
            msg.append("Created:\n" + "\n".join(created))
        if failed:
            msg.append("Failed:\n" + "\n".join([f"row {r}: {err}" for r, err in failed]))
        QMessageBox.information(self, "Header Export", "\n\n".join(msg) if msg else "Nothing to do.")

    def open_output_dir(self):
        # Prefer explicit out dir; else use first item's src folder
        target = self.out_dir_edit.text().strip()
        if not target and self.table.items:
            target = os.path.dirname(self.table.items[0]["path"])
        if not target:
            QMessageBox.information(self, "Info", "No output directory to open.")
            return
        url = QUrl.fromLocalFile(target)
        QDesktopServices.openUrl(url)

    def choose_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Select MIDI files", "",
                                                "MIDI files (*.mid *.midi)")
        if files:
            self.table.add_files(files)

# ---- Main window with tabs ----

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Audio Toolkit — WAV/BIN & MIDI PPQN")
        self.resize(1024, 660)

        tabs = QTabWidget()
        tabs.addTab(BinBeatsPage(), "WAV → BIN (Offsets)")
        tabs.addTab(MidiPPQNPage(), "MIDI PPQN Converter")

        self.setCentralWidget(tabs)

def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()