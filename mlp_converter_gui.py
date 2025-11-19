# -*- coding: utf-8 -*-
"""
JSON -> C 'MLP_Model' struct formatter GUI (PySide6) - English UI

- 把 JSON 中的简单 MLP 描述转成 C 代码
- 你可以按自己的 C 结构体格式修改 to_c_struct 函数
"""

import json
from pathlib import Path
import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenuBar,
    QMessageBox,
    QPushButton,
    QFileDialog,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


def format_float(v: float) -> str:
    """格式化 float 为 C 代码形式."""
    return f"{float(v):.8f}f"


def _flatten_2d(mat):
    return [x for row in mat for x in row]


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

    Output example:

    static const MLP_Model Powerball_mlp __attribute__((aligned(4))) =
    {
        .layer1_weights = { ... },
        .layer1_biases  = { ... },
        .layer2_weights = { ... },
        .layer2_biases  = { ... },
        ...
    };
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
        """
        idx: 1-based layer index
        layerSizes: [size_0, size_1, ..., size_N], N = numberOfLayers
        对应关系: 第 idx 层: in_size = layerSizes[idx-1], out_size = layerSizes[idx]
        """
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
    """支持拖放 .json 文件的文本框."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setPlaceholderText("Paste JSON here, or drag a .json file.")

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() or event.mimeData().hasText():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls() or event.mimeData().hasText():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                path = url.toLocalFile()
                if path.lower().endswith(".json"):
                    try:
                        text = Path(path).read_text(encoding="utf-8")
                        self.setPlainText(text)

                        # ---- 新增：自动设置 model_name ----
                        parent = self.parentWidget()
                        if parent is not None and hasattr(parent, "name_edit"):
                            base = Path(path).stem                      # 文件名（不含扩展名）
                            safe = re.sub(r"[^0-9a-zA-Z_]", "_", base)   # 转成 C 合法变量名
                            if re.match(r"^[0-9]", safe):
                                safe = "_" + safe
                            if safe:
                                parent.name_edit.setText(safe)

                    except Exception as e:
                        QMessageBox.warning(self, "Error", f"Failed to read file:\n{e}")

            event.acceptProposedAction()
        elif event.mimeData().hasText():
            # 粘贴 JSON 的情况，不自动改 model_name
            self.setPlainText(event.mimeData().text())
            event.acceptProposedAction()
        else:
            super().dropEvent(event)


class OutputWindow(QMainWindow):
    """显示 C 代码的输出窗口."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("C Output")
        self.resize(800, 600)

        self.text = QTextEdit(self)
        self.text.setReadOnly(True)
        self.setCentralWidget(self.text)

        self._create_menu()

    def _create_menu(self):
        menubar = QMenuBar(self)
        self.setMenuBar(menubar)

        file_menu = menubar.addMenu("&File")
        act_save = QAction("Save as...", self)
        act_save.triggered.connect(self.save_as)
        file_menu.addAction(act_save)

    def set_code(self, code: str):
        self.text.setPlainText(code)

    def save_as(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save C file",
            "",
            "C/Headers (*.c *.h);;All files (*.*)",
        )
        if not path:
            return
        try:
            Path(path).write_text(self.text.toPlainText(), encoding="utf-8")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to save file:\n{e}")


class MlpConverterWidget(QWidget):
    """可嵌入的 JSON -> C MLP 转换 Widget."""

    def __init__(self, parent=None):
        super().__init__(parent)

        self.output_win = OutputWindow(self)

        layout = QVBoxLayout(self)

        title = QLabel("<b>JSON → C struct (MLP_Model)</b>")
        title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        layout.addWidget(title)

        # 模型名
        row_name = QHBoxLayout()
        row_name.addWidget(QLabel("Model name:"))
        self.name_edit = QLineEdit("mlp_model")
        row_name.addWidget(self.name_edit, 1)

        self.btnPasteSample = QPushButton("Paste sample JSON")
        row_name.addWidget(self.btnPasteSample)
        layout.addLayout(row_name)

        # JSON 编辑框
        self.input_edit = DropTextEdit()
        layout.addWidget(self.input_edit, 1)

        # 按钮行
        btn_row = QHBoxLayout()
        self.btnOpen = QPushButton("Open JSON file…")
        self.btnConvert = QPushButton("Convert")
        self.btnClear = QPushButton("Clear")
        self.btnShowOutput = QPushButton("Show output window")

        btn_row.addWidget(self.btnOpen)
        btn_row.addWidget(self.btnConvert)
        btn_row.addWidget(self.btnClear)
        btn_row.addWidget(self.btnShowOutput)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        # 连接
        self.btnOpen.clicked.connect(self.open_file)
        self.btnConvert.clicked.connect(self.convert_now)
        self.btnClear.clicked.connect(self.input_edit.clear)
        self.btnShowOutput.clicked.connect(self.output_win.show)
        self.btnPasteSample.clicked.connect(self.paste_sample)

    # ----------------------
    # 槽函数
    # ----------------------

    def paste_sample(self):
        sample = {
                    "numberOfLayers": 3,
                    "layerSizes": [
                        1,
                        2,
                        2,
                        1
                    ],
                    "weightsAndBiases": [
                        {
                        "weights": [
                            -0.8486694,
                            -0.7875375
                        ],
                        "biases": [
                            0.0318286,
                            0.0288779
                        ]
                        },
                        {
                        "weights": [
                            0.3420051,
                            0.2937841,
                            0.6676209,
                            0.6437992
                        ],
                        "biases": [
                            -0.0059032,
                            0.0135505
                        ]
                        },
                        {
                        "weights": [
                            -0.4156123,
                            -0.7425233
                        ],
                        "biases": [
                            0.0532713
                        ]
                        }
                    ]
                    }
        self.input_edit.setPlainText(json.dumps(sample, indent=2))

    def open_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open JSON file",
            "",
            "JSON files (*.json);;All files (*.*)",
        )
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8")
            self.input_edit.setPlainText(text)

            # --- 新增：根据文件名自动设置 model_name ---
            base = Path(path).stem                        # 文件名（无扩展名）
            safe = re.sub(r"[^0-9a-zA-Z_]", "_", base)    # 变成 C 合法变量名
            if re.match(r"^[0-9]", safe):
                safe = "_" + safe
            if safe:
                self.name_edit.setText(safe)

        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to read file:\n{e}")

    def convert_now(self):
        model_name = self.name_edit.text().strip()
        if not model_name:
            QMessageBox.warning(self, "Error", "Model name cannot be empty.")
            return

        text = self.input_edit.toPlainText()
        if not text.strip():
            QMessageBox.warning(self, "Error", "JSON input is empty.")
            return

        try:
            code = to_c_struct(text, model_name)
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to generate C code:\n{e}")
            return

        self.output_win.set_code(code)
        self.output_win.show()


class MainWindow(QMainWindow):
    """单独运行本文件时用到的主窗口."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("JSON → C 'MLP_Model' formatter - PySide6")
        self.resize(900, 650)

        widget = MlpConverterWidget(self)
        self.setCentralWidget(widget)


def main():
    import sys

    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
