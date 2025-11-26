# -*- coding: utf-8 -*-
"""
EQ converter inside amp_tools package.
"""

import json
import re
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QTextEdit, QPushButton,
    QFileDialog, QMessageBox, QGroupBox
)


def format_float(v):
    return f"{float(v):.12f}"


class EqConverterWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)

        title = QLabel("<b>EQ Matrix → C Code Generator</b>")
        layout.addWidget(title)

        # Input box with consistent styling
        box_in = QGroupBox("Input (2D JSON array)")
        box_in.setStyleSheet(
            "QGroupBox { border: 1px solid #cccccc; border-radius: 4px; margin-top: 8px; padding-top: 8px; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px 0 3px; }"
        )
        v_in = QVBoxLayout(box_in)
        
        self.input_edit = QTextEdit()
        self.input_edit.setPlaceholderText("Paste 2D JSON array here...")
        v_in.addWidget(self.input_edit)
        layout.addWidget(box_in)

        hbtn = QHBoxLayout()
        self.btnOpen = QPushButton("Open JSON…")
        self.btnConvert = QPushButton("Convert")
        self.btnClear = QPushButton("Clear")

        hbtn.addWidget(self.btnOpen)
        hbtn.addWidget(self.btnConvert)
        hbtn.addWidget(self.btnClear)
        hbtn.addStretch(1)
        layout.addLayout(hbtn)

        # Output box with consistent styling
        box_out = QGroupBox("Output (C Code)")
        box_out.setStyleSheet(
            "QGroupBox { border: 1px solid #cccccc; border-radius: 4px; margin-top: 8px; padding-top: 8px; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px 0 3px; }"
        )
        v_out = QVBoxLayout(box_out)
        
        self.output_edit = QTextEdit()
        self.output_edit.setReadOnly(True)
        v_out.addWidget(self.output_edit)
        layout.addWidget(box_out)

        self.btnOpen.clicked.connect(self.open_file)
        self.btnConvert.clicked.connect(self.convert_data)
        self.btnClear.clicked.connect(self.input_edit.clear)

    def open_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open JSON file", "", "JSON files (*.json);;All files (*.*)")
        if not path:
            return
        try:
            txt = open(path, "r", encoding="utf-8").read()
            self.input_edit.setPlainText(txt)
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to load file:\n{e}")

    def convert_data(self):
        txt = self.input_edit.toPlainText().strip()
        if not txt:
            QMessageBox.warning(self, "Error", "Input is empty.")
            return
        try:
            arr = json.loads(txt)
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Invalid JSON:\n{e}")
            return
        if not isinstance(arr, list) or not isinstance(arr[0], list):
            QMessageBox.warning(self, "Error", "Top-level JSON must be a 2D array.")
            return
        rows = len(arr)
        cols = len(arr[0])
        eq_switch = f".eq_switch = (uint8_t[]){{{','.join('1' for _ in range(rows))}}},"
        lines = []
        lines.append(f".eq_coeff = (float [][{cols}]){{")
        for row in arr:
            lines.append("    {")
            for v in row:
                lines.append(f"        {format_float(v)},")
            lines.append("    },")
        lines.append("};")
        code = eq_switch + "\n" + "\n".join(lines)
        self.output_edit.setPlainText(code)
