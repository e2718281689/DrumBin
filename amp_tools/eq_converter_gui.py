# -*- coding: utf-8 -*-
"""
EQ converter inside amp_tools package.
"""

import json
import os
from PySide6.QtCore import Qt
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

        # ✅ 允许窗口接收拖拽
        self.setAcceptDrops(True)

        layout = QVBoxLayout(self)

        title = QLabel("<b>EQ Matrix → C Code Generator</b>")
        layout.addWidget(title)

        # Input box with consistent styling
        box_in = QGroupBox("Input (2D JSON array)  —  可拖拽 JSON 文件到这里")
        box_in.setStyleSheet(
            "QGroupBox { border: 1px solid #cccccc; border-radius: 4px; margin-top: 8px; padding-top: 8px; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px 0 3px; }"
        )
        v_in = QVBoxLayout(box_in)

        self.input_edit = QTextEdit()
        self.input_edit.setPlaceholderText("Paste 2D JSON array here... 或拖拽 .json 文件进来")
        # ✅ QTextEdit 本身也允许拖拽（有些平台仅对控件生效）
        self.input_edit.setAcceptDrops(True)
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

    # =========================
    # ✅ Drag & Drop 支持
    # =========================
    def dragEnterEvent(self, event):
        md = event.mimeData()
        if md.hasUrls():
            # 只要是本地文件就接受（drop 时再做扩展名/内容校验）
            for url in md.urls():
                if url.isLocalFile():
                    event.acceptProposedAction()
                    return
        # 也允许拖文本（例如从编辑器拖一段 JSON）
        if md.hasText():
            event.acceptProposedAction()
            return

        event.ignore()

    def dropEvent(self, event):
        md = event.mimeData()

        # 1) 拖文件
        if md.hasUrls():
            # 只取第一个文件（如需多文件可自行循环）
            for url in md.urls():
                if not url.isLocalFile():
                    continue
                path = url.toLocalFile()
                if path:
                    self._load_json_file(path)
                    event.acceptProposedAction()
                    return

        # 2) 拖文本
        if md.hasText():
            self.input_edit.setPlainText(md.text())
            event.acceptProposedAction()
            return

        event.ignore()

    def _load_json_file(self, path: str):
        # 可选：限制扩展名
        ext = os.path.splitext(path)[1].lower()
        if ext not in (".json", ""):
            QMessageBox.warning(self, "Error", f"Not a JSON file:\n{path}")
            return
        try:
            txt = open(path, "r", encoding="utf-8").read()
            self.input_edit.setPlainText(txt)
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to load file:\n{e}")

    # =========================
    # 原逻辑
    # =========================
    def open_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open JSON file", "", "JSON files (*.json);;All files (*.*)")
        if not path:
            return
        self._load_json_file(path)

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
        if not isinstance(arr, list) or not arr or not isinstance(arr[0], list):
            QMessageBox.warning(self, "Error", "Top-level JSON must be a 2D array.")
            return

        rows = len(arr)
        cols = len(arr[0])

        # 可选：检查每行列数一致，避免生成错误
        for i, row in enumerate(arr):
            if not isinstance(row, list) or len(row) != cols:
                QMessageBox.warning(self, "Error", f"Row {i} has different column count.")
                return

        eq_switch = f"    .eq_switch = (uint8_t[]){{{','.join('1' for _ in range(rows))}}},"
        lines = []
        lines.append(f"    .eq_coeff = (float [][{cols}]){{")
        for row in arr:
            lines.append("        {")
            for v in row:
                lines.append(f"            {format_float(v)},")
            lines.append("        },")
        lines.append("    }")
        code = eq_switch + "\n" + "\n".join(lines)
        self.output_edit.setPlainText(code)
