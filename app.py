# app.py
import sys, os, json, csv
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QPushButton, QTableWidget, QTableWidgetItem,
    QFileDialog, QMessageBox, QLabel, QHBoxLayout, QAbstractItemView, QSpinBox, QCheckBox
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication

def read_file_size(path: str) -> int:
    return os.path.getsize(path)

def is_wav(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            riff = f.read(12)
            return len(riff) >= 12 and riff[0:4] == b"RIFF" and riff[8:12] == b"WAVE"
    except Exception:
        return False

def compute_offsets(files, align_bytes: int):
    """files: list[(path,size)] -> list[offset] with alignment between items"""
    offsets = []
    acc = 0
    for i, (_, size) in enumerate(files):
        offsets.append(acc)
        acc += size
        if align_bytes > 1 and i < len(files) - 1:
            pad = (-acc) % align_bytes
            acc += pad
    return offsets

class DropTable(QTableWidget):
    def __init__(self, parent=None):
        super().__init__(0, 4, parent)
        self.setHorizontalHeaderLabels(["Index", "Filename", "Offset (hex)", "Offset (dec)"])
        self.setAcceptDrops(True)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.files = []  # list of (path, size)
        self.align_bytes = 1
        self.use_hex = True
        self.resizeColumnsToContents()

    # ---- DnD ----
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
    def add_files(self, paths):
        added = 0
        for p in paths:
            if not os.path.isfile(p):
                continue
            if not is_wav(p):
                continue
            size = read_file_size(p)
            self.files.append((p, size))
            added += 1
        if added == 0:
            QMessageBox.information(self, "Info", "No valid WAV files found.")
        self.refresh_table()

    def clear_files(self):
        self.files.clear()
        self.setRowCount(0)

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
        if not rows or rows[0] == len(self.files)-1:
            return
        for r in rows:
            self.files[r+1], self.files[r] = self.files[r], self.files[r+1]
        self.selectRow(rows[0]+1)
        self.refresh_table()

    # ---- Export/Copy ----
    def export_bin(self):
        if not self.files:
            QMessageBox.warning(self, "Warning", "No files to export.")
            return
        out, _ = QFileDialog.getSaveFileName(self, "Save BIN", "out.bin", "BIN files (*.bin)")
        if not out:
            return
        try:
            with open(out, "wb") as w:
                acc = 0
                for i, (p, size) in enumerate(self.files):
                    with open(p, "rb") as f:
                        w.write(f.read())
                    acc += size
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
            writer.writerow(["index", "filename", "offset_hex", "offset_dec"])
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

class MainWin(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("BinBeats - WAV to BIN")
        self.resize(900, 560)

        self.table = DropTable(self)

        # Controls
        btn_add = QPushButton("Add WAV...")
        btn_clear = QPushButton("Clear")
        btn_up = QPushButton("Move Up")
        btn_down = QPushButton("Move Down")
        btn_export = QPushButton("Build BIN")

        btn_copy_plain = QPushButton("Copy Offsets")
        btn_copy_c = QPushButton("Copy C Array")
        btn_csv = QPushButton("Export CSV")
        btn_json = QPushButton("Export JSON")

        # Alignment + Hex toggle
        self.align_spin = QSpinBox()
        self.align_spin.setRange(1, 4096)
        self.align_spin.setValue(1)
        self.align_spin.setSingleStep(1)
        self.align_spin.setToolTip("Alignment (bytes) between files")

        self.hex_check = QCheckBox("Hex")
        self.hex_check.setChecked(True)

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

        tips = QLabel("Tip: Drag & drop WAV files here. Offsets are computed from BIN start, respecting alignment.")
        tips.setStyleSheet("color: gray;")

        lay = QVBoxLayout(self)
        lay.addLayout(bar1)
        lay.addLayout(bar2)
        lay.addWidget(self.table)
        lay.addWidget(tips)

    def on_align_changed(self, v):
        # snap to common values 1/2/4/8/16 if you like; here we keep free-range
        self.table.align_bytes = max(1, int(v))
        self.table.refresh_table()

    def on_hex_changed(self, state):
        self.table.use_hex = (state == Qt.Checked)
        # 仅显示列内容的 hex/dec？这里保持两列都显示；复制时根据 Hex 勾选来决定格式
        # 如果你希望表格也只展示一种，可在这里切换列可见性

    def choose_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Select WAV files", "", "WAV files (*.wav)")
        if files:
            self.table.add_files(files)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MainWin()
    win.show()
    sys.exit(app.exec())
