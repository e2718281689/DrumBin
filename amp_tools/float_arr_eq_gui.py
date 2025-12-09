# main.py
import sys
import numpy as np

from PySide6.QtCore import Qt
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPlainTextEdit, QPushButton,
    QListWidget, QListWidgetItem, QLabel, QFormLayout, QComboBox,
    QDoubleSpinBox, QMessageBox, QGroupBox
)

from .dsp.blt_biquad import (
    FILTER_TYPES,
    rbj_biquad,
    apply_biquad_df2t,
    parse_numbers,
    format_c_array,
)


COMMON_SAMPLE_RATES = [22050, 44100, 48000, 96000, 192000]


class FilterDescriptor:
    def __init__(self, type_: str = 'lowpass', freq: float = 1000.0, Q: float = None, gain: float = 0.0):
        self.type = type_
        self.freq = float(freq)
        if Q is None:
            self.Q = float(1.0 / np.sqrt(2.0)) if type_ in ('lowpass', 'highpass') else 1.0
        else:
            self.Q = float(Q)
        self.gain = float(gain)

    def label(self) -> str:
        t = self.type
        if t in ('peaking', 'lowshelf', 'highshelf'):
            return f"{t}  f={self.freq:g}Hz  Q={self.Q:g}  g={self.gain:g}dB"
        return f"{t}  f={self.freq:g}Hz  Q={self.Q:g}"


class FloatArrEqWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Biquad Filter GUI (Library separated + SR presets + editable)")
        self.filters: list[FilterDescriptor] = []

        root = QVBoxLayout(self)

        # --- Top: Sample Rate chooser (preset + editable) ---
        top = QHBoxLayout()
        top.addWidget(QLabel("Sample Rate (Hz):"))

        self.fs_combo = QComboBox()
        self.fs_combo.setEditable(True)
        self.fs_combo.addItems([str(v) for v in COMMON_SAMPLE_RATES])
        self.fs_combo.setCurrentText("44100")

        # only allow integer input
        self.fs_combo.setInsertPolicy(QComboBox.NoInsert)
        self.fs_combo.lineEdit().setValidator(QIntValidator(8000, 768000, self))
        self.fs_combo.lineEdit().setPlaceholderText("e.g. 44100")

        top.addWidget(self.fs_combo)
        top.addStretch(1)

        self.btn_process = QPushButton("Process")
        self.btn_process.clicked.connect(self.on_process)
        top.addWidget(self.btn_process)

        self.btn_clear = QPushButton("Clear")
        self.btn_clear.clicked.connect(self.on_clear)
        top.addWidget(self.btn_clear)

        root.addLayout(top)

        # --- Middle layout ---
        mid = QHBoxLayout()

        # Input
        input_box = QGroupBox("Input Array (plain text)")
        input_layout = QVBoxLayout(input_box)
        self.input_edit = QPlainTextEdit()
        self.input_edit.setPlaceholderText("Paste numbers here: {1, 2, 3} / 1,2,3 / lines ...")
        input_layout.addWidget(self.input_edit)
        mid.addWidget(input_box, 2)

        # Filters
        filt_box = QGroupBox("Filters (cascade)")
        filt_layout = QVBoxLayout(filt_box)

        self.list_widget = QListWidget()
        self.list_widget.currentRowChanged.connect(self.on_select_filter)
        filt_layout.addWidget(self.list_widget)

        btn_row = QHBoxLayout()
        self.btn_add = QPushButton("+ Add")
        self.btn_apply = QPushButton("Apply / Update")
        self.btn_remove = QPushButton("- Remove")
        self.btn_up = QPushButton("Up")
        self.btn_down = QPushButton("Down")

        self.btn_add.clicked.connect(self.add_filter_from_editor)
        self.btn_apply.clicked.connect(self.apply_editor_to_selected)
        self.btn_remove.clicked.connect(self.remove_filter)
        self.btn_up.clicked.connect(self.move_up)
        self.btn_down.clicked.connect(self.move_down)

        btn_row.addWidget(self.btn_add)
        btn_row.addWidget(self.btn_apply)
        btn_row.addWidget(self.btn_remove)
        btn_row.addWidget(self.btn_up)
        btn_row.addWidget(self.btn_down)
        filt_layout.addLayout(btn_row)

        # Editor
        form = QFormLayout()
        self.type_combo = QComboBox()
        self.type_combo.addItems(FILTER_TYPES)
        self.type_combo.currentTextChanged.connect(self.on_editor_changed)

        self.freq_spin = QDoubleSpinBox()
        self.freq_spin.setDecimals(3)
        self.freq_spin.setRange(0.1, 1e9)
        self.freq_spin.setValue(1000.0)
        self.freq_spin.valueChanged.connect(self.on_editor_changed)

        self.Q_spin = QDoubleSpinBox()
        self.Q_spin.setDecimals(6)
        self.Q_spin.setRange(0.001, 1e6)
        self.Q_spin.setValue(1.0 / np.sqrt(2.0))
        self.Q_spin.valueChanged.connect(self.on_editor_changed)

        self.gain_spin = QDoubleSpinBox()
        self.gain_spin.setDecimals(3)
        self.gain_spin.setRange(-60.0, 60.0)
        self.gain_spin.setValue(0.0)
        self.gain_spin.valueChanged.connect(self.on_editor_changed)

        form.addRow("Type:", self.type_combo)
        form.addRow("Freq (Hz):", self.freq_spin)
        form.addRow("Q:", self.Q_spin)
        form.addRow("Gain (dB):", self.gain_spin)
        filt_layout.addLayout(form)

        hint = QLabel(
            "Workflow:\n"
            "1) Adjust settings (draft)\n"
            "2) + Add to append\n"
            "3) Select in list -> edit\n"
            "4) Apply/Update to save"
        )
        hint.setStyleSheet("opacity: 0.75;")
        filt_layout.addWidget(hint)

        mid.addWidget(filt_box, 2)

        # Output
        out_box = QGroupBox("Output Array (C format, 8 per line)")
        out_layout = QVBoxLayout(out_box)
        self.output_edit = QPlainTextEdit()
        self.output_edit.setReadOnly(True)
        out_layout.addWidget(self.output_edit)
        mid.addWidget(out_box, 2)

        root.addLayout(mid)

        # Initialize editor draft
        self.set_editor_from_filter(FilterDescriptor())

    # ---- Sample rate ----
    def get_fs(self) -> float:
        txt = (self.fs_combo.currentText() or "").strip()
        if not txt:
            raise ValueError("Sample rate is empty.")

        try:
            fs = int(txt)
        except ValueError:
            raise ValueError("Sample rate must be an integer.")

        if fs < 20 or fs > 192000:
            raise ValueError("Sample rate out of range (20..192000).")

        return float(fs)

    # ---- Editor helpers ----
    def update_gain_enabled(self):
        t = self.type_combo.currentText()
        self.gain_spin.setEnabled(t in ('peaking', 'lowshelf', 'highshelf'))

    def on_editor_changed(self, *_):
        self.update_gain_enabled()
        t = self.type_combo.currentText()
        # small convenience: if user switches to LP/HP and Q == 1, nudge to 0.707 (doesn't override custom values)
        if t in ('lowpass', 'highpass') and abs(self.Q_spin.value() - 1.0) < 1e-12:
            self.Q_spin.blockSignals(True)
            self.Q_spin.setValue(1.0 / np.sqrt(2.0))
            self.Q_spin.blockSignals(False)

    def editor_to_filter(self) -> FilterDescriptor:
        return FilterDescriptor(
            type_=self.type_combo.currentText(),
            freq=float(self.freq_spin.value()),
            Q=float(self.Q_spin.value()),
            gain=float(self.gain_spin.value())
        )

    def set_editor_from_filter(self, f: FilterDescriptor):
        self.type_combo.blockSignals(True)
        self.freq_spin.blockSignals(True)
        self.Q_spin.blockSignals(True)
        self.gain_spin.blockSignals(True)

        self.type_combo.setCurrentText(f.type)
        self.freq_spin.setValue(f.freq)
        self.Q_spin.setValue(f.Q)
        self.gain_spin.setValue(f.gain)

        self.type_combo.blockSignals(False)
        self.freq_spin.blockSignals(False)
        self.Q_spin.blockSignals(False)
        self.gain_spin.blockSignals(False)

        self.update_gain_enabled()

    # ---- List helpers ----
    def current_filter(self):
        idx = self.list_widget.currentRow()
        if idx < 0 or idx >= len(self.filters):
            return None, -1
        return self.filters[idx], idx

    # ---- Actions ----
    def add_filter_from_editor(self):
        f = self.editor_to_filter()
        self.filters.append(f)
        self.list_widget.addItem(QListWidgetItem(f.label()))
        self.list_widget.setCurrentRow(self.list_widget.count() - 1)

    def apply_editor_to_selected(self):
        f, idx = self.current_filter()
        if f is None:
            QMessageBox.information(self, "No selection", "Select a filter in the list first.")
            return

        newf = self.editor_to_filter()
        f.type, f.freq, f.Q, f.gain = newf.type, newf.freq, newf.Q, newf.gain
        self.list_widget.item(idx).setText(f.label())

    def remove_filter(self):
        _, idx = self.current_filter()
        if idx < 0:
            return
        self.filters.pop(idx)
        self.list_widget.takeItem(idx)
        if self.filters:
            self.list_widget.setCurrentRow(min(idx, len(self.filters) - 1))

    def move_up(self):
        _, idx = self.current_filter()
        if idx <= 0:
            return
        self.filters[idx - 1], self.filters[idx] = self.filters[idx], self.filters[idx - 1]
        item = self.list_widget.takeItem(idx)
        self.list_widget.insertItem(idx - 1, item)
        self.list_widget.setCurrentRow(idx - 1)
        # refresh labels
        for i, ff in enumerate(self.filters):
            self.list_widget.item(i).setText(ff.label())

    def move_down(self):
        _, idx = self.current_filter()
        if idx < 0 or idx >= len(self.filters) - 1:
            return
        self.filters[idx + 1], self.filters[idx] = self.filters[idx], self.filters[idx + 1]
        item = self.list_widget.takeItem(idx)
        self.list_widget.insertItem(idx + 1, item)
        self.list_widget.setCurrentRow(idx + 1)
        for i, ff in enumerate(self.filters):
            self.list_widget.item(i).setText(ff.label())

    def on_select_filter(self, row: int):
        if row < 0 or row >= len(self.filters):
            return
        self.set_editor_from_filter(self.filters[row])

    def on_clear(self):
        self.input_edit.clear()
        self.output_edit.clear()

    def on_process(self):
        try:
            fs = self.get_fs()
        except Exception as e:
            QMessageBox.warning(self, "Bad sample rate", str(e))
            return

        x = parse_numbers(self.input_edit.toPlainText())
        if x.size == 0:
            QMessageBox.warning(self, "No data", "No valid numbers found in input.")
            return
        if not self.filters:
            QMessageBox.information(self, "No filters", "Filter list is empty. Add at least one filter.")
            return

        nyq = fs / 2.0
        for f in self.filters:
            if not (0.0 < f.freq < nyq):
                QMessageBox.warning(
                    self, "Bad frequency",
                    f"Filter freq must be within (0, Nyquist).\nNyquist={nyq:g} Hz\nGot {f.freq:g} Hz ({f.type})"
                )
                return

        y = x.copy()
        try:
            for f in self.filters:
                b, a = rbj_biquad(f.type, fs, f.freq, Q=f.Q, gain_db=f.gain)
                y = apply_biquad_df2t(y, b, a)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Processing failed:\n{e}")
            return

        self.output_edit.setPlainText(format_c_array(y, per_line=8))

