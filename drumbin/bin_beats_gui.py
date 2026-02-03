# -*- coding: utf-8 -*-
"""
WAV -> BIN (Offsets) Page - Slot Based UI
"""

import sys
import os
import json
import soundfile as sf
import numpy as np
from typing import Dict, Optional, List, Any
from .bin_generator import BinGenerator

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, 
    QScrollArea, QFrame, QFileDialog, QMessageBox, QDialog,
    QProgressBar, QSizePolicy, QApplication
)
from PySide6.QtCore import Qt, Signal, QUrl, QTimer, QSize
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QIcon, QColor, QPalette, QAction
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput

# ---- Constants & Config ----

CONFIG_FILE = "drum_slots_config.json"

DEFAULT_MAP = {
    36: "底鼓 (Kick)",
    38: "军鼓中心 (Center Snare)",
    37: "军鼓边击 (Rim Snare)",
    42: "闭镲 (Close Hat)",
    46: "开镲 (Open Hat)",
    44: "踩镲 (Pedal Hat)",
    51: "叮叮镲镲面 (Bow Ride)",
    53: "叮叮镲镲帽 (Bell Ride)",
    49: "吊镲 (Crash)",
    50: "通鼓1 (Tom 1)",
    47: "通鼓2 (Tom 2)",
    43: "通鼓3 (Tom 3)"
}

def get_drum_name(midi_id: int) -> str:
    return DEFAULT_MAP.get(midi_id, f"音符 {midi_id} (Note {midi_id})")

def show_toast(parent, message, duration=2000):
    """Simple Toast-like notification using QDialog"""
    d = QDialog(parent)
    d.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.ToolTip)
    d.setAttribute(Qt.WA_TranslucentBackground)
    d.setAttribute(Qt.WA_ShowWithoutActivating)
    
    layout = QVBoxLayout(d)
    label = QLabel(message)
    label.setStyleSheet("""
        QLabel {
            background-color: #333333;
            color: white;
            padding: 10px;
            border-radius: 5px;
            font-size: 14px;
        }
    """)
    layout.addWidget(label)
    d.adjustSize()
    
    # Position logic (center bottom of parent)
    if parent:
        geo = parent.geometry()
        x = geo.x() + (geo.width() - d.width()) // 2
        y = geo.y() + geo.height() - d.height() - 50
        d.move(x, y)
    
    d.show()
    QTimer.singleShot(duration, d.close)

# ---- Slot Widget ----

class DrumSlotWidget(QFrame):
    file_changed = Signal(int, str) # midi_id, new_path (or None)
    
    def __init__(self, midi_id: int):
        super().__init__()
        self.midi_id = midi_id
        self.file_path: Optional[str] = None
        self.duration_sec: float = 0.0
        
        self.setFrameShape(QFrame.StyledPanel)
        self.setFrameShadow(QFrame.Raised)
        self.setAcceptDrops(True)
        self.setFixedHeight(50)
        
        # UI Components
        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 2, 5, 2)
        
        # 1. MIDI ID
        self.lbl_id = QLabel(f"{midi_id}")
        self.lbl_id.setFixedWidth(30)
        self.lbl_id.setAlignment(Qt.AlignCenter)
        self.lbl_id.setStyleSheet("font-weight: bold; color: #555;")
        
        # 2. Name
        self.lbl_name = QLabel(get_drum_name(midi_id))
        self.lbl_name.setFixedWidth(180)
        self.lbl_name.setStyleSheet("color: #333;")
        
        # 3. Play Button
        self.btn_play = QPushButton("▶")
        self.btn_play.setFixedSize(24, 24) # Slightly larger for usability, icon is 16x16
        self.btn_play.clicked.connect(self.toggle_play)
        self.btn_play.setEnabled(False)
        
        # 4. File Info
        self.lbl_file = QLabel("拖入 WAV 文件...")
        self.lbl_file.setStyleSheet("color: #888; font-style: italic;")
        self.lbl_file.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        
        # 5. Progress Bar (Mini)
        self.progress = QProgressBar()
        self.progress.setFixedWidth(100)
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setVisible(False)
        
        # 6. Delete Button
        self.btn_delete = QPushButton("✕")
        self.btn_delete.setFixedSize(24, 24)
        self.btn_delete.setToolTip("移除文件 (Remove File)")
        self.btn_delete.clicked.connect(self.clear_file)
        self.btn_delete.setEnabled(False)
        self.btn_delete.setStyleSheet("QPushButton { color: #d32f2f; font-weight: bold; }")

        layout.addWidget(self.lbl_id)
        layout.addWidget(self.lbl_name)
        layout.addWidget(self.btn_play)
        layout.addWidget(self.lbl_file)
        layout.addWidget(self.progress)
        layout.addWidget(self.btn_delete)
        
        # Audio Player
        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)
        
        self.player.positionChanged.connect(self.on_position_changed)
        self.player.mediaStatusChanged.connect(self.on_media_status_changed)
        
        # Timer for 100ms update (Qt6 QMediaPlayer emits positionChanged regularly)
        # If needed, we can use a QTimer to query position, but usually signal is enough.
        
    def set_file(self, path: str, confirm_override=False):
        if self.file_path and self.file_path != path and confirm_override:
            # Signal parent to handle confirmation logic if needed, 
            # or just handle it here. 
            # Parent handles the global logic, here we just update if told to.
            pass
            
        # Validation
        valid, msg = self.validate_wav(path)
        if not valid:
            show_toast(self.window(), f"文件无效: {msg}")
            self.set_style_invalid()
            QTimer.singleShot(1000, self.reset_style)
            return False

        # Success
        self.file_path = path
        try:
            info = sf.info(path)
            self.duration_sec = info.duration
            self.lbl_file.setText(f"{os.path.basename(path)} ({self.duration_sec:.2f}s)")
            self.lbl_file.setStyleSheet("color: black;")
            self.btn_play.setEnabled(True)
            self.btn_delete.setEnabled(True)
            self.file_changed.emit(self.midi_id, path)
            self.reset_style()
            return True
        except Exception as e:
            show_toast(self.window(), f"读取错误: {e}")
            return False

    def clear_file(self):
        """Remove file from slot"""
        self.file_path = None
        self.duration_sec = 0.0
        self.lbl_file.setText("拖入 WAV 文件...")
        self.lbl_file.setStyleSheet("color: #888; font-style: italic;")
        self.btn_play.setEnabled(False)
        self.btn_delete.setEnabled(False)
        
        # Stop playback if playing
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.stop()
            self.btn_play.setText("▶")
            self.progress.setVisible(False)
            
        self.reset_style()
        self.file_changed.emit(self.midi_id, None)

    def validate_wav(self, path: str) -> (bool, str):
        if not os.path.exists(path):
            return False, "文件不存在"
        try:
            info = sf.info(path)
            if info.format != 'WAV':
                return False, "非 WAV 格式"
            # Strict sample rate check removed per user request
            # if info.samplerate not in [44100, 48000]:
            #    return False, f"不支持的采样率: {info.samplerate}Hz (仅支持 44.1/48kHz)"
            # sf.info subtype can be 'PCM_16', 'PCM_24', 'FLOAT', etc.
            if info.subtype not in ['PCM_16', 'PCM_24']:
                 return False, f"不支持的位深: {info.subtype} (仅支持 16/24-bit)"
            return True, ""
        except Exception as e:
            return False, str(e)

    def toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.stop()
            self.btn_play.setText("▶")
            self.progress.setVisible(False)
        else:
            if not self.file_path:
                return
            self.player.setSource(QUrl.fromLocalFile(self.file_path))
            self.audio_output.setVolume(1.0)
            self.player.play()
            self.btn_play.setText("⏹")
            self.progress.setVisible(True)

    def on_position_changed(self, pos):
        if self.player.duration() > 0:
            pct = int((pos / self.player.duration()) * 100)
            self.progress.setValue(pct)

    def on_media_status_changed(self, status):
        if status == QMediaPlayer.EndOfMedia:
            self.btn_play.setText("▶")
            self.progress.setVisible(False)
            self.progress.setValue(0)

    # ---- Drag & Drop ----
    
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            # Check first file
            urls = event.mimeData().urls()
            if urls:
                path = urls[0].toLocalFile()
                valid, _ = self.validate_wav(path)
                if valid:
                    self.set_style_valid()
                    event.acceptProposedAction()
                else:
                    self.set_style_invalid()
                    event.ignore() # Or accept to show the red feedback? 
                    # If we ignore, cursor changes to forbidden. 
                    # Requirement: "非法文件变红". So we accept drag but show red.
                    event.acceptProposedAction() 
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self.reset_style()

    def dropEvent(self, event: QDropEvent):
        self.reset_style()
        urls = event.mimeData().urls()
        if not urls:
            return
            
        path = urls[0].toLocalFile()
        
        # Check overwrite
        if self.file_path:
            ret = QMessageBox.question(
                self, "覆盖确认", 
                f"槽位 {self.midi_id} 已有文件：\n{os.path.basename(self.file_path)}\n\n是否替换为：\n{os.path.basename(path)}?",
                QMessageBox.Yes | QMessageBox.No
            )
            if ret != QMessageBox.Yes:
                return
        
        self.set_file(path)

    # ---- Styling ----
    
    def set_style_valid(self):
        self.setStyleSheet("DrumSlotWidget { border: 2px solid #4CAF50; background-color: #E8F5E9; }")

    def set_style_invalid(self):
        self.setStyleSheet("DrumSlotWidget { border: 2px solid #F44336; background-color: #FFEBEE; }")
        
    def reset_style(self):
        if not self.file_path:
             # Empty style
             self.setStyleSheet("DrumSlotWidget { border: 1px solid #ccc; background-color: #f9f9f9; }")
        else:
             # Occupied style
             self.setStyleSheet("DrumSlotWidget { border: 1px solid #aaa; background-color: #fff; }")
             
    def set_error_highlight(self):
        self.setStyleSheet("DrumSlotWidget { border: 2px solid red; background-color: #FFCDD2; }")


# ---- Main Page ----

class BinBeatsPage(QWidget):
    def __init__(self):
        super().__init__()
        
        # Data
        self.slots: Dict[int, DrumSlotWidget] = {}
        
        # Layout
        main_layout = QVBoxLayout(self)
        
        # Toolbar
        toolbar = QHBoxLayout()
        btn_export = QPushButton("生成 BIN (Offsets)")
        btn_export.clicked.connect(self.export_bin)
        btn_reload = QPushButton("重置/清空")
        btn_reload.clicked.connect(self.reset_all)
        
        toolbar.addWidget(btn_reload)
        toolbar.addStretch()
        toolbar.addWidget(btn_export)
        
        main_layout.addLayout(toolbar)
        
        # Scroll Area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_content = QWidget()
        self.scroll_layout = QVBoxLayout(scroll_content)
        self.scroll_layout.setSpacing(2)
        self.scroll_layout.setContentsMargins(0,0,0,0)
        
        # Create Slots
        # Only show slots defined in DEFAULT_MAP
        self.active_midi_ids = sorted(DEFAULT_MAP.keys())
        
        for i in self.active_midi_ids:
            slot = DrumSlotWidget(i)
            slot.file_changed.connect(self.save_config)
            self.scroll_layout.addWidget(slot)
            self.slots[i] = slot
            
        self.scroll_layout.addStretch()
        scroll.setWidget(scroll_content)
        main_layout.addWidget(scroll)
        
        # Load Config
        QTimer.singleShot(100, self.load_config)

    def load_config(self):
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for midi_str, path in data.items():
                        midi_id = int(midi_str)
                        if midi_id in self.slots and os.path.exists(path):
                            self.slots[midi_id].set_file(path)
        except Exception as e:
            print(f"Config load error: {e}")

    def save_config(self):
        data = {}
        for midi_id, slot in self.slots.items():
            if slot.file_path:
                data[str(midi_id)] = slot.file_path
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Config save error: {e}")

    def reset_all(self):
        ret = QMessageBox.warning(self, "确认", "确定要清空所有槽位吗？", QMessageBox.Yes | QMessageBox.No)
        if ret == QMessageBox.Yes:
            for slot in self.slots.values():
                slot.file_path = None
                slot.lbl_file.setText("拖入 WAV 文件...")
                slot.lbl_file.setStyleSheet("color: #888; font-style: italic;")
                slot.btn_play.setEnabled(False)
                slot.reset_style()
            self.save_config()

    def export_bin(self):
        # 1. Validation
        occupied_slots = []
        errors = False
        
        for slot in self.slots.values():
            if slot.file_path:
                # Validate file existence
                if not os.path.exists(slot.file_path):
                    slot.set_error_highlight()
                    errors = True
                else:
                    occupied_slots.append(slot)
        
        if errors:
            QMessageBox.critical(self, "导出失败", "请补全红色槽位（文件丢失或无效）")
            return
            
        if not occupied_slots:
            QMessageBox.warning(self, "警告", "没有配置任何文件")
            return

        # 2. Select Output
        out_path, _ = QFileDialog.getSaveFileName(self, "导出 BIN", "drums.bin", "BIN Files (*.bin)")
        if not out_path:
            return
            
        # 3. Generate
        try:
            generator = BinGenerator()
            # Iterate active_midi_ids to maintain order
            for i in self.active_midi_ids:
                slot = self.slots.get(i)
                if slot and slot.file_path and os.path.exists(slot.file_path):
                    generator.add_file(i, slot.file_path)
            
            base_path = os.path.splitext(out_path)[0]
            stats = generator.generate(out_path, base_path)
            
            # 4. Show Result
            msg_text = (
                f"导出成功！\n\n"
                f"总大小: {stats['total_size']} 字节 ({stats['total_size']/1024:.2f} KB)\n"
                f"样本数: {stats['wav_count']} 个\n\n"
                f"偏移表已保存至:\n"
                f"{os.path.basename(base_path)}_layout.h"
            )
            
            msg = QMessageBox(self)
            msg.setWindowTitle("导出完成")
            msg.setText(msg_text)
            btn_open = msg.addButton("打开目录", QMessageBox.ActionRole)
            msg.addButton(QMessageBox.Ok)
            msg.exec()
            
            if msg.clickedButton() == btn_open:
                os.startfile(os.path.dirname(out_path))
                
        except Exception as e:
            QMessageBox.critical(self, "导出错误", f"导出过程中发生错误:\n{e}")

