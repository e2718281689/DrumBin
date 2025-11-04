# -*- coding: utf-8 -*-
"""
JSON -> C 'MLP_Model' struct formatter GUI (PySide6) - English UI
Author: ChatGPT
Usage:
    pip install PySide6
    python mlp_converter_gui_en.py
"""

import json
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase, QFont, QAction
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTextEdit,
    QPushButton,
    QLabel,
    QFileDialog,
    QMessageBox,
    QLineEdit,
    QStatusBar,
)


APP_TITLE = "JSON → C Struct Converter (PySide6)"


def format_float(val) -> str:
    """Keep 7 decimal places to match the example."""
    try:
        f = float(val)
        return f"{f:.7f}"
    except Exception:
        return str(val)


def to_c_struct(json_text: str, model_name: str = "Powerball_mlp") -> str:
    """
    Convert the given JSON into the required C struct initializer.

    Expected JSON schema:
    {
      "numberOfLayers": 3,
      "layerSizes": [1, 2, 2, 1],
      "weightsAndBiases": [
        {"weights":[...], "biases":[...]},
        ...
      ]
    }
    """
    data = json.loads(json_text)

    wab = data.get("weightsAndBiases")
    if not isinstance(wab, list) or not wab:
        raise ValueError("Missing or invalid 'weightsAndBiases' list.")

    layer_sizes = data.get("layerSizes")

    lines = []
    header = f"static const MLP_Model {model_name} __attribute__((aligned(4))) = \n{{"
    lines.append(header)

    # Optional validation against layerSizes
    def _validate_layer(idx: int, weights, biases):
        if not layer_sizes or not isinstance(layer_sizes, list) or len(layer_sizes) < 2:
            return  # no validation info available
        try:
            in_size = int(layer_sizes[idx - 1])
            out_size = int(layer_sizes[idx])
            expected_w = in_size * out_size
            expected_b = out_size
            if len(weights) != expected_w or len(biases) != expected_b:
                return (f"// [warning] layer {idx} size mismatch: "
                        f"weights={len(weights)}/{expected_w}, biases={len(biases)}/{expected_b}")
        except Exception:
            return None
        return None

    warnings = []

    for i, layer in enumerate(wab, start=1):
        weights = layer.get("weights", [])
        biases = layer.get("biases", [])

        w_txt = ", ".join(format_float(w) for w in weights)
        b_txt = ", ".join(format_float(b) for b in biases)

        lines.append(f"    .layer{i}_weights = {{ {w_txt} }},")
        lines.append(f"    .layer{i}_biases  = {{ {b_txt} }},")

        warn = _validate_layer(i, weights, biases)
        if warn:
            warnings.append(warn)

    lines.append("};")

    if warnings:
        lines.append("")
        lines.extend(warnings)

    return "\n".join(lines)


class DropTextEdit(QTextEdit):
    """A text box that accepts drag-and-drop text/files."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setAcceptDrops(True)
        self.setPlaceholderText("Drop a JSON file here, or paste JSON...")
        fixed = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        fixed.setPointSize(11)
        self.setFont(fixed)

    def dragEnterEvent(self, event):
        md = event.mimeData()
        if md.hasUrls() or md.hasText():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        event.acceptProposedAction()

    def dropEvent(self, event):
        md = event.mimeData()
        if md.hasUrls():
            for url in md.urls():
                if url.isLocalFile():
                    path = Path(url.toLocalFile())
                    try:
                        text = path.read_text(encoding="utf-8")
                    except UnicodeDecodeError:
                        # Fallback for non-UTF8 text files
                        text = path.read_text(encoding="latin-1", errors="replace")
                    self.setPlainText(text)
                    break
        elif md.hasText():
            self.setPlainText(md.text())
        else:
            super().dropEvent(event)


class OutputWindow(QMainWindow):
    """Shows the converted C code; supports copy and save."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Converted Output")
        self.resize(720, 540)

        central = QWidget()
        vbox = QVBoxLayout(central)

        self.info_label = QLabel("Converted C struct:")
        vbox.addWidget(self.info_label)

        self.text = QTextEdit()
        self.text.setReadOnly(True)
        fixed = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        fixed.setPointSize(11)
        self.text.setFont(fixed)
        vbox.addWidget(self.text, 1)

        btn_row = QHBoxLayout()
        self.copy_btn = QPushButton("Copy to Clipboard")
        self.save_btn = QPushButton("Save as .c / .txt")
        btn_row.addWidget(self.copy_btn)
        btn_row.addWidget(self.save_btn)
        btn_row.addStretch(1)
        vbox.addLayout(btn_row)

        self.setCentralWidget(central)

        self.copy_btn.clicked.connect(self.copy_to_clipboard)
        self.save_btn.clicked.connect(self.save_to_file)
        self.setStatusBar(QStatusBar())

    def set_code(self, code: str):
        self.text.setPlainText(code)

    def copy_to_clipboard(self):
        QApplication.clipboard().setText(self.text.toPlainText())
        self.statusBar().showMessage("Copied to clipboard.", 2000)

    def save_to_file(self):
        default_name = "mlp_model.c"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save As",
            default_name,
            "C/Text Files (*.c *.txt);;All Files (*)",
        )
        if path:
            try:
                Path(path).write_text(self.text.toPlainText(), encoding="utf-8")
                self.statusBar().showMessage(f"Saved: {path}", 3000)
            except Exception as e:
                QMessageBox.critical(self, "Save Failed", f"Failed to write file:\n{e}")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(820, 620)

        self.output_win = OutputWindow()

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        title = QLabel("<b>JSON → C Struct (MLP_Model)</b>")
        title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        layout.addWidget(title)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Model name:"))
        self.name_edit = QLineEdit("Powerball_mlp")
        name_row.addWidget(self.name_edit, 1)

        paste_btn = QPushButton("Paste sample")
        paste_btn.clicked.connect(self._paste_sample)
        name_row.addWidget(paste_btn)

        layout.addLayout(name_row)

        self.input_edit = DropTextEdit()
        layout.addWidget(self.input_edit, 1)

        btn_row = QHBoxLayout()
        self.open_btn = QPushButton("Open file…")
        self.convert_btn = QPushButton("Convert")
        self.clear_btn = QPushButton("Clear")
        self.show_out_btn = QPushButton("Show Output Window")

        btn_row.addWidget(self.open_btn)
        btn_row.addWidget(self.convert_btn)
        btn_row.addWidget(self.clear_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(self.show_out_btn)
        layout.addLayout(btn_row)

        self.status = QStatusBar()
        self.setStatusBar(self.status)

        self.open_btn.clicked.connect(self.open_file)
        self.convert_btn.clicked.connect(self.convert_now)
        self.clear_btn.clicked.connect(self.input_edit.clear)
        self.show_out_btn.clicked.connect(self.output_win.show)

        self._build_menu()

    def _build_menu(self):
        open_act = QAction("Open...", self)
        open_act.triggered.connect(self.open_file)
        convert_act = QAction("Convert", self)
        convert_act.triggered.connect(self.convert_now)
        quit_act = QAction("Quit", self)
        quit_act.triggered.connect(self.close)

        menubar = self.menuBar()
        file_menu = menubar.addMenu("File")
        file_menu.addAction(open_act)
        file_menu.addSeparator()
        file_menu.addAction(quit_act)
        act_menu = menubar.addMenu("Actions")
        act_menu.addAction(convert_act)

    def _paste_sample(self):
        sample = """{
  "numberOfLayers": 3,
  "layerSizes": [1, 2, 2, 1],
  "weightsAndBiases": [
    {
      "weights": [-4.4042091, -1.4905028],
      "biases":  [0.0002749, 0.0171433]
    },
    {
      "weights": [-1.5123240, -0.6680719, -3.9269865, -1.0470184],
      "biases":  [0.0126598, 0.0192005]
    },
    {
      "weights": [-0.8399458, 1.3878489],
      "biases":  [0.0004549]
    }
  ]
}"""
        self.input_edit.setPlainText(sample)

    def open_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose JSON file",
            "",
            "JSON Files (*.json);;Text Files (*.txt);;All Files (*)",
        )
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = Path(path).read_text(encoding="latin-1", errors="replace")
        self.input_edit.setPlainText(text)

    def convert_now(self):
        raw = self.input_edit.toPlainText().strip()
        if not raw:
            QMessageBox.information(self, "Info", "Please paste or drop JSON content first.")
            return
        name = self.name_edit.text().strip() or "Powerball_mlp"
        try:
            code = to_c_struct(raw, name)
        except Exception as e:
            QMessageBox.critical(self, "Conversion Failed", f"Parse/convert error:\n{e}")
            return

        self.output_win.set_code(code)
        self.output_win.show()
        self.status.showMessage("Conversion completed.", 2000)


def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
