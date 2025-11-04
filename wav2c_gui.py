# -*- coding: utf-8 -*-
"""
PySide6 GUI: Drag-and-drop WAV -> C-style float array (.h)
- 默认输出到源文件同目录；也可自选输出目录
- 立体声自动转单声道（取均值）
- 支持 8/16/24/32-bit PCM
- 可截取合并单声道后的前 N 个采样点（N=0 表示全部）
"""

import os
import re
import wave
import traceback
from typing import Optional

import numpy as np

from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QPushButton, QTableWidget, QTableWidgetItem,
    QFileDialog, QMessageBox, QLabel, QHBoxLayout, QAbstractItemView, QSpinBox, QCheckBox,
    QLineEdit, QMainWindow
)
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices


# ---------- 音频读取与转换 ----------
def wav_to_float_mono(filepath):
    with wave.open(filepath, 'rb') as wf:
        n_channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        framerate = wf.getframerate()
        n_frames = wf.getnframes()
        frames = wf.readframes(n_frames)

    # 转 numpy 浮点 [-1,1]
    if sampwidth == 1:
        data = np.frombuffer(frames, dtype=np.uint8).astype(np.float32)
        data = (data - 128.0) / 128.0
    elif sampwidth == 2:
        data = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    elif sampwidth == 3:
        a = np.frombuffer(frames, dtype=np.uint8).reshape(-1, 3)
        tmp = (a[:, 0].astype(np.int32) |
               (a[:, 1].astype(np.int32) << 8) |
               (a[:, 2].astype(np.int32) << 16))
        # 24-bit 符号扩展
        mask = tmp & 0x800000
        tmp = tmp - (mask << 1)
        data = tmp.astype(np.float32) / 8388608.0
    elif sampwidth == 4:
        data = np.frombuffer(frames, dtype=np.int32).astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f"Unsupported sample width: {sampwidth} bytes")

    if n_channels > 1:
        data = data.reshape(-1, n_channels).mean(axis=1)

    return data.astype(np.float32), framerate


def sanitize_var_name(name: str) -> str:
    base = re.sub(r'[^A-Za-z0-9_]', '_', name)
    if not base:
        base = 'pcm_data'
    if base[0].isdigit():
        base = '_' + base
    return base


def to_c_array_str(arr: np.ndarray, var_name: str, samplerate: Optional[int] = None, per_line: int = 10) -> str:
    header = ""
    if samplerate is not None:
        header += f"// Sample rate: {int(samplerate)} Hz\n"
    header += f"// Length: {len(arr)} samples (mono, float32, range [-1, 1])\n"
    header += f"static const float {var_name}[] = {{\n"
    for i in range(0, len(arr), per_line):
        line = ", ".join(f"{x:.6f}" for x in arr[i:i+per_line])
        header += f"    {line}"
        if i + per_line < len(arr):
            header += ","
        header += "\n"
    header += "};\n"
    return header


# ---------- 拖拽表格 ----------
class DropTable(QTableWidget):
    def __init__(self, parent=None):
        super().__init__(0, 3, parent)
        self.setHorizontalHeaderLabels(["WAV file", "Output .h", "Status"])
        self.setAcceptDrops(True)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.horizontalHeader().setStretchLastSection(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        paths = []
        for u in urls:
            p = u.toLocalFile()
            if os.path.isdir(p):
                for root, _, files in os.walk(p):
                    for f in files:
                        if f.lower().endswith(".wav"):
                            paths.append(os.path.join(root, f))
            elif p.lower().endswith(".wav"):
                paths.append(p)
        if paths:
            self.add_files(paths)

    def add_files(self, paths):
        existed = set()
        for r in range(self.rowCount()):
            existed.add(self.item(r, 0).text())
        added = 0
        for p in paths:
            if p not in existed:
                r = self.rowCount()
                self.insertRow(r)
                self.setItem(r, 0, QTableWidgetItem(p))
                self.setItem(r, 1, QTableWidgetItem(""))
                self.setItem(r, 2, QTableWidgetItem("Queued"))
                added += 1
        return added

    def clear_rows(self):
        self.setRowCount(0)


# ---------- 主窗体 ----------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("WAV → C float array (.h) - PySide6")
        self.resize(900, 560)

        central = QWidget(self)
        self.setCentralWidget(central)
        v = QVBoxLayout(central)

        # 顶部：输出目录选项
        top = QHBoxLayout()
        self.chkSameDir = QCheckBox("Use same directory as each file (default)")
        self.chkSameDir.setChecked(True)
        self.outEdit = QLineEdit()
        self.outEdit.setPlaceholderText("Select an output directory (disabled when using same dir)")
        self.outEdit.setEnabled(False)
        self.btnBrowse = QPushButton("Browse...")
        self.btnBrowse.setEnabled(False)
        top.addWidget(self.chkSameDir)
        top.addWidget(self.outEdit, 1)
        top.addWidget(self.btnBrowse)
        v.addLayout(top)

        # 第二行：N 截取
        rowN = QHBoxLayout()
        rowN.addWidget(QLabel("Take first N samples (after mono):"))
        self.spinN = QSpinBox()
        self.spinN.setRange(0, 10_000_000)
        self.spinN.setValue(0)
        rowN.addWidget(self.spinN)
        rowN.addWidget(QLabel("0 means all"))
        rowN.addStretch(1)
        v.addLayout(rowN)

        # 表格（拖拽）
        self.table = DropTable()
        v.addWidget(self.table, 1)

        # 底部按钮与状态
        bottom = QHBoxLayout()
        self.btnAdd = QPushButton("Add WAV...")
        self.btnClear = QPushButton("Clear list")
        self.btnOpenOut = QPushButton("Open output dir")
        self.btnOpenOut.setEnabled(False)
        bottom.addWidget(self.btnAdd)
        bottom.addWidget(self.btnClear)
        bottom.addStretch(1)
        bottom.addWidget(self.btnOpenOut)
        self.btnConvert = QPushButton("Convert to .h")
        bottom.addWidget(self.btnConvert)
        v.addLayout(bottom)

        self.status = QLabel("Ready.")
        v.addWidget(self.status)

        # 信号
        self.chkSameDir.toggled.connect(self._toggle_same_dir)
        self.btnBrowse.clicked.connect(self._choose_outdir)
        self.btnOpenOut.clicked.connect(self._open_outdir)
        self.btnAdd.clicked.connect(self._add_dialog)
        self.btnClear.clicked.connect(self.table.clear_rows)
        self.btnConvert.clicked.connect(self._convert_all)

        # 状态
        self.fixed_out_dir: Optional[str] = None

    # ---- 槽函数 ----
    def _toggle_same_dir(self, checked: bool):
        self.outEdit.setEnabled(not checked)
        self.btnBrowse.setEnabled(not checked)
        self.btnOpenOut.setEnabled(not checked and bool(self.fixed_out_dir))
        if checked:
            self.outEdit.clear()
        self.status.setText("Output: same as each WAV" if checked else "Output: custom directory")

    def _choose_outdir(self):
        d = QFileDialog.getExistingDirectory(self, "Choose output directory")
        if d:
            self.fixed_out_dir = d
            self.outEdit.setText(d)
            self.btnOpenOut.setEnabled(True)
            self.status.setText(f"Output directory: {d}")

    def _open_outdir(self):
        if self.fixed_out_dir and os.path.isdir(self.fixed_out_dir):
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.fixed_out_dir))

    def _add_dialog(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Select WAV files", "", "WAV files (*.wav)")
        if files:
            added = self.table.add_files(files)
            self.status.setText(f"Added {added} file(s).")

    def _convert_all(self):
        rows = self.table.rowCount()
        if rows == 0:
            QMessageBox.information(self, "Info", "Please add or drag WAV files into the list.")
            return

        use_same_dir = self.chkSameDir.isChecked()
        if not use_same_dir and not self.fixed_out_dir:
            QMessageBox.warning(self, "Warning", "Please choose an output directory or enable 'Use same directory'.")
            return

        n_take = self.spinN.value()
        ok, fail = 0, 0
        for r in range(rows):
            wav_path = self.table.item(r, 0).text()
            try:
                out_path = self._process_one(wav_path, n_take, use_same_dir)
                self.table.setItem(r, 1, QTableWidgetItem(out_path))
                self.table.setItem(r, 2, QTableWidgetItem("OK"))
                self.table.item(r, 2).setForeground(Qt.green)
                ok += 1
            except Exception as e:
                self.table.setItem(r, 2, QTableWidgetItem("ERROR"))
                self.table.item(r, 2).setForeground(Qt.red)
                fail += 1
                print(f"[ERROR] {wav_path}\n{e}\n{traceback.format_exc()}")

        self.status.setText(f"Done. Success: {ok}, Failed: {fail}")
        if fail:
            QMessageBox.warning(self, "Finished with errors", f"Success: {ok}, Failed: {fail}")
        else:
            QMessageBox.information(self, "Finished", f"All done. Success: {ok}")

    # ---- 核心处理 ----
    def _process_one(self, wav_path: str, n_take: int, use_same_dir: bool) -> str:
        data, sr = wav_to_float_mono(wav_path)
        if n_take > 0:
            data = data[:n_take]

        stem = os.path.splitext(os.path.basename(wav_path))[0]
        var_name = sanitize_var_name(stem) + "_pcm"
        c_text = to_c_array_str(data, var_name=var_name, samplerate=sr, per_line=10)

        if use_same_dir:
            out_dir = os.path.dirname(wav_path)
        else:
            out_dir = self.fixed_out_dir or os.path.dirname(wav_path)

        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f"{sanitize_var_name(stem)}.h")

        with open(out_path, "w", encoding="utf-8") as f:
            f.write("#pragma once\n\n")
            f.write(c_text)

        return out_path


def main():
    import sys
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
