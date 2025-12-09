# -*- coding: utf-8 -*-
"""
Main GUI app inside amp_tools package.
"""

import sys

from PySide6.QtWidgets import QApplication, QMainWindow, QTabWidget, QStatusBar

from .wav2c_gui import Wav2CWidget
from .mlp_converter_gui import MlpConverterWidget
from .eq_converter_gui import EqConverterWidget
from .float2wav_gui import Float2WavWidget
from .float_arr_eq_gui import FloatArrEqWidget


class MainApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Audio & MLP Tools - PySide6 (amp_tools)")
        self.resize(1100, 700)

        tabs = QTabWidget(self)
        self.setCentralWidget(tabs)

        self.tab_wav = Wav2CWidget()
        self.tab_f2w = Float2WavWidget()
        self.tab_mlp = MlpConverterWidget()
        self.tab_eq = EqConverterWidget()
        self.tab_ir_eq = FloatArrEqWidget()

        tabs.addTab(self.tab_eq, "EQ Matrix → C")
        tabs.addTab(self.tab_wav, "WAV → C array")
        tabs.addTab(self.tab_f2w, "Float array → WAV")
        tabs.addTab(self.tab_mlp, "JSON → MLP_Model")
        tabs.addTab(self.tab_ir_eq, "ir → eq → ir")

        self.status = QStatusBar(self)
        self.setStatusBar(self.status)
        self.status.showMessage("Ready.")


def main():
    app = QApplication(sys.argv)
    win = MainApp()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
