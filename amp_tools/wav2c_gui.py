# -*- coding: utf-8 -*-
"""
WAV -> C float array widget (moved into amp_tools package).
"""

import os
import re
from typing import Optional

import numpy as np
import soundfile as sf

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStatusBar,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QMainWindow,
)


def sanitize_var_name(name: str) -> str:
    base = os.path.splitext(os.path.basename(name))[0]
    base = re.sub(r"[^0-9a-zA-Z_]", "_", base)
    if re.match(r"^[0-9]", base):
        base = "_" + base
    if not base:
        base = "wav_data"
    return base


def wav_to_mono_float(path: str, max_samples: int = 0) -> tuple[np.ndarray, int]:
    data, sr = sf.read(path, always_2d=True, dtype="float32")
    mono = data.mean(axis=1)
    if max_samples > 0:
        mono = mono[:max_samples]
    return mono, sr


def to_c_array_header(samples: np.ndarray, sr: int, var_name: str) -> str:
    header_guard = re.sub(r"[^0-9A-Z_]", "_", var_name.upper()) + "_H"
    lines = []
    lines.append(f"#ifndef {header_guard}")
    lines.append(f"#define {header_guard}")
    lines.append("")
    lines.append("/*")
    lines.append(f" * Generated from WAV file")
    lines.append(f" * Sample rate : {sr} Hz")
    lines.append(f" * Length      : {len(samples)} samples")
    lines.append(" */")
    lines.append("")
    lines.append("/* clang-format off */")
    lines.append(f"static const int {var_name}_sr = {sr};")
    lines.append(f"static const int {var_name}_len = {len(samples)};")
    lines.append(f"static const float {var_name}[] = {{")

    row = []
    for i, v in enumerate(samples):
        row.append(f"{v:.8f}")
        if (i + 1) % 8 == 0:
            lines.append("    " + ", ".join(row) + ",")
            row = []
    if row:
        lines.append("    " + ", ".join(row) + ",")

    lines.append("};")
    lines.append("/* clang-format on */")
    lines.append("")
    lines.append(f"#endif /* {header_guard} */")
    lines.append("")
    return "\n".join(lines)


class WavDropList(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setSelectionMode(QListWidget.ExtendedSelection)
        self.setAlternatingRowColors(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if not event.mimeData().hasUrls():
            return super().dropEvent(event)
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith(".wav"):
                self.add_path(path)
        event.acceptProposedAction()

    def add_path(self, path: str):
        for i in range(self.count()):
            if self.item(i).data(Qt.UserRole) == path:
                return
        item = QListWidgetItem(os.path.basename(path))
        item.setToolTip(path)
        item.setData(Qt.UserRole, path)
        self.addItem(item)

    def paths(self) -> list[str]:
        return [self.item(i).data(Qt.UserRole) for i in range(self.count())]


class Wav2CWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.fixed_out_dir: Optional[str] = None

        main_layout = QVBoxLayout(self)

        box_out = QGroupBox("Output directory")
        g = QGridLayout(box_out)

        self.chkSameDir = QCheckBox("Use the same directory as each WAV file")
        self.chkSameDir.setChecked(True)
        g.addWidget(self.chkSameDir, 0, 0, 1, 3)

        g.addWidget(QLabel("Fixed output directory:"), 1, 0)
        self.outEdit = QLineEdit()
        self.outEdit.setPlaceholderText("Choose output directory (disabled when using same dir)")
        self.outEdit.setEnabled(False)
        g.addWidget(self.outEdit, 1, 1)

        self.btnBrowse = QPushButton("Browse…")
        self.btnBrowse.setEnabled(False)
        g.addWidget(self.btnBrowse, 1, 2)

        main_layout.addWidget(box_out)

        box_opts = QGroupBox("Options")
        hopt = QHBoxLayout(box_opts)

        hopt.addWidget(QLabel("Max samples (0 = all):"))
        self.spnMaxSamples = QSpinBox()
        self.spnMaxSamples.setRange(0, 10_000_000)
        self.spnMaxSamples.setValue(0)
        hopt.addWidget(self.spnMaxSamples)

        hopt.addStretch(1)
        main_layout.addWidget(box_opts)

        box_files = QGroupBox("WAV files (drag here or use 'Add files…')")
        vfiles = QVBoxLayout(box_files)

        self.lstFiles = WavDropList()
        vfiles.addWidget(self.lstFiles)

        hbtn = QHBoxLayout()
        self.btnAddFiles = QPushButton("Add files…")
        self.btnRemoveSel = QPushButton("Remove selected")
        self.btnClearAll = QPushButton("Clear all")
        hbtn.addWidget(self.btnAddFiles)
        hbtn.addWidget(self.btnRemoveSel)
        hbtn.addWidget(self.btnClearAll)
        hbtn.addStretch(1)
        vfiles.addLayout(hbtn)

        main_layout.addWidget(box_files, 1)

        hbottom = QHBoxLayout()
        self.btnConvert = QPushButton("Convert to .h")
        self.btnClearLog = QPushButton("Clear Log")
        hbottom.addWidget(self.btnConvert)
        hbottom.addWidget(self.btnClearLog)
        hbottom.addStretch(1)
        main_layout.addLayout(hbottom)

        self.logEdit = QTextEdit()
        self.logEdit.setReadOnly(True)
        self.logEdit.setPlaceholderText("Log output…")
        main_layout.addWidget(self.logEdit, 1)

        self.btnClearLog.clicked.connect(self.logEdit.clear)
        self.chkSameDir.toggled.connect(self._toggle_same_dir)
        self.btnBrowse.clicked.connect(self._choose_outdir)
        self.btnAddFiles.clicked.connect(self._add_files)
        self.btnRemoveSel.clicked.connect(self._remove_selected)
        self.btnClearAll.clicked.connect(self.lstFiles.clear)
        self.btnConvert.clicked.connect(self._convert_all)

    def _log(self, msg: str):
        self.logEdit.append(msg)

    def _toggle_same_dir(self, checked: bool):
        self.outEdit.setEnabled(not checked)
        self.btnBrowse.setEnabled(not checked)
        if checked:
            self.fixed_out_dir = None

    def _choose_outdir(self):
        d = QFileDialog.getExistingDirectory(self, "Choose output directory")
        if d:
            self.fixed_out_dir = d
            self.outEdit.setText(d)

    def _add_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Choose WAV files", "", "WAV files (*.wav)")
        for f in files:
            self.lstFiles.add_path(f)

    def _remove_selected(self):
        for item in self.lstFiles.selectedItems():
            row = self.lstFiles.row(item)
            self.lstFiles.takeItem(row)

    def _get_outdir_for_file(self, path: str) -> str:
        if self.chkSameDir.isChecked() or not self.fixed_out_dir:
            return os.path.dirname(path)
        return self.fixed_out_dir

    def _convert_all(self):
        files = self.lstFiles.paths()
        if not files:
            QMessageBox.warning(self, "No files", "Please add some WAV files first.")
            return

        max_samples = self.spnMaxSamples.value()

        ok_count = 0
        for path in files:
            try:
                self._log(f"Processing: {path}")
                samples, sr = wav_to_mono_float(path, max_samples=max_samples)
                var_name = sanitize_var_name(path)
                code = to_c_array_header(samples, sr, var_name)

                out_dir = self._get_outdir_for_file(path)
                os.makedirs(out_dir, exist_ok=True)
                out_name = os.path.splitext(os.path.basename(path))[0] + ".h"
                out_path = os.path.join(out_dir, out_name)

                with open(out_path, "w", encoding="utf-8") as f:
                    f.write(code)

                self._log(f"  => Saved: {out_path}")
                ok_count += 1
            except Exception as e:
                self._log(f"  !! Error: {e!r}")

        self._log(f"\nDone. {ok_count} / {len(files)} file(s) converted.")

        if ok_count == len(files):
            QMessageBox.information(self, "Done", "All files converted successfully.")
        else:
            QMessageBox.warning(self, "Finished with errors", f"Converted {ok_count} / {len(files)} files. See log for details.")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("WAV → C float array (.h) - PySide6")
        self.resize(900, 600)

        widget = Wav2CWidget(self)
        self.setCentralWidget(widget)

        self.status = QStatusBar(self)
        self.setStatusBar(self.status)
        self.status.showMessage("Ready.")


def main():
    import sys

    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
