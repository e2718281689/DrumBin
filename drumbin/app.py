# -*- coding: utf-8 -*-
"""
Audio Toolkit — WAV/BIN & MIDI PPQN & Audio Cleaner
"""

import sys
from PySide6.QtWidgets import QApplication, QMainWindow, QTabWidget

# Import decoupled pages
from .cleaner_gui import CleanerWidget
from .bin_beats_gui import BinBeatsPage
from .midi_ppqn_gui import MidiPPQNPage


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Audio Toolkit — WAV/BIN & MIDI PPQN")
        self.resize(1024, 660)

        tabs = QTabWidget()
        tabs.addTab(CleanerWidget(), "Audio Cleaner")
        tabs.addTab(BinBeatsPage(), "WAV → BIN (Offsets)")
        tabs.addTab(MidiPPQNPage(), "MIDI PPQN Converter")

        self.setCentralWidget(tabs)

def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
