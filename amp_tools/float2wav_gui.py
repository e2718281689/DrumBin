from typing import Optional

import os

import numpy as np

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .wav_utils import parse_float_array, float_array_to_wav


class Float2WavWidget(QWidget):
    """Floating-point array to WAV widget."""

    def __init__(self, parent=None):
        super().__init__(parent)

        self.out_path: Optional[str] = None

        main = QVBoxLayout(self)

        box_in = QGroupBox("Float array input")
        g = QVBoxLayout(box_in)
        self.editArray = QTextEdit()
        self.editArray.setPlaceholderText(
            "Paste a Python list or C array here, e.g. [0.0, 0.1, -0.1, ...]"
        )
        g.addWidget(self.editArray)

        main.addWidget(box_in, 1)

        box_opts = QGroupBox("Options")
        go = QGridLayout(box_opts)

        go.addWidget(QLabel("Sample rate (Hz):"), 0, 0)
        self.spnSR = QSpinBox()
        self.spnSR.setRange(100, 192000)
        self.spnSR.setValue(44100)
        go.addWidget(self.spnSR, 0, 1)

        go.addWidget(QLabel("Bit depth:"), 1, 0)
        self.bitDepth = QLineEdit("16")
        self.bitDepth.setMaximumWidth(80)
        go.addWidget(self.bitDepth, 1, 1)

        main.addWidget(box_opts)

        hbtn = QHBoxLayout()
        self.btnChoose = QPushButton("Choose output file…")
        self.btnWrite = QPushButton("Write WAV")
        self.btnClearLog = QPushButton("Clear Log")
        hbtn.addWidget(self.btnChoose)
        hbtn.addWidget(self.btnWrite)
        hbtn.addWidget(self.btnClearLog)
        hbtn.addStretch(1)
        main.addLayout(hbtn)

        self.outEdit = QLineEdit()
        self.outEdit.setReadOnly(True)
        main.addWidget(self.outEdit)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        main.addWidget(self.log, 1)

        # signals
        self.btnChoose.clicked.connect(self._choose_out)
        self.btnWrite.clicked.connect(self._write_wav)
        self.btnClearLog.clicked.connect(self.log.clear)

    def _log(self, msg: str):
        self.log.append(msg)

    def _choose_out(self):
        path, _ = QFileDialog.getSaveFileName(self, "Choose WAV file", "", "WAV files (*.wav)")
        if path:
            if not path.lower().endswith(".wav"):
                path += ".wav"
            self.out_path = path
            self.outEdit.setText(path)

    def _write_wav(self):
        text = self.editArray.toPlainText().strip()
        if not text:
            QMessageBox.warning(self, "No data", "Please paste a float array first.")
            return

        arr = parse_float_array(text)
        if arr.size == 0:
            QMessageBox.warning(self, "Parse error", "Could not find any numbers in the input.")
            return

        sr = int(self.spnSR.value())
        try:
            bd = int(self.bitDepth.text().strip())
        except Exception:
            QMessageBox.warning(self, "Invalid bit depth", "Bit depth must be an integer (16,24,32).")
            return

        out = self.out_path
        if not out:
            out, _ = QFileDialog.getSaveFileName(self, "Choose WAV file", "", "WAV files (*.wav)")
            if not out:
                return
            if not out.lower().endswith(".wav"):
                out += ".wav"
            self.out_path = out
            self.outEdit.setText(out)

        try:
            float_array_to_wav(arr, sr, out, bit_depth=bd)
            self._log(f"Saved: {out} ({arr.size} samples, {sr} Hz, {bd}-bit)")
            QMessageBox.information(self, "Done", f"WAV saved: {os.path.basename(out)}")
        except Exception as e:
            self._log(f"Error: {e!r}")
            QMessageBox.critical(self, "Error", f"Failed to write WAV: {e}")
