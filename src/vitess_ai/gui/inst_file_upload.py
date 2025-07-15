#!/usr/bin/env python3
"""
Simple Instrument File Manager for Simple File List Manager for Vitess Read-In module
"""

import sys
import os
import json
from typing import Optional
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QFileDialog, QMessageBox, QGroupBox,
    QTextEdit
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

class InstrumentFileManager(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Vitess AI Agent - Instrument File")
        self.setGeometry(100, 100, 700, 400)
        self.setMinimumSize(500, 300)
        
        # File storage
        self.instrument_file_path: Optional[str] = None
        self.last_directory = os.path.expanduser("~")
        
        # Apply monochrome style
        self.apply_monochrome_style()
        
        # Initialize UI
        self.setup_ui()
        
    def apply_monochrome_style(self):
        """Apply monochrome color scheme"""
        style = """
        QMainWindow {
            background-color: #f5f5f5;
            color: #2d2d2d;
        }
        QWidget {
            background-color: #f5f5f5;
            color: #2d2d2d;
        }
        QPushButton {
            background-color: #e0e0e0;
            color: #2d2d2d;
            border: 1px solid #bdbdbd;
            padding: 8px 16px;
            border-radius: 4px;
            font-weight: bold;
        }
        QPushButton:hover {
            background-color: #d0d0d0;
        }
        QPushButton:pressed {
            background-color: #c0c0c0;
        }
        QLineEdit {
            background-color: #ffffff;
            border: 1px solid #bdbdbd;
            border-radius: 4px;
            padding: 6px;
            font-family: 'Consolas', monospace;
        }
        QTextEdit {
            background-color: #ffffff;
            border: 1px solid #bdbdbd;
            border-radius: 4px;
            padding: 6px;
            font-family: 'Consolas', monospace;
        }
        QGroupBox {
            font-weight: bold;
            border: 1px solid #bdbdbd;
            border-radius: 4px;
            margin-top: 10px;
            padding-top: 10px;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            subcontrol-position: top left;
            padding: 0 8px;
            background-color: #f5f5f5;
        }
        QLabel {
            color: #2d2d2d;
        }
        """
        self.setStyleSheet(style)
        
    def setup_ui(self):
        """Setup the main user interface"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Main layout
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(15, 15, 15, 15)
        
        # Title
        title_label = QLabel("Read-in Module -- Instrument File Manager")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(title_label)
        
        # File selection panel
        file_panel = self.create_file_panel()
        main_layout.addWidget(file_panel)
        
        # File info panel
        info_panel = self.create_info_panel()
        main_layout.addWidget(info_panel)
        
        # Status bar
        self.statusBar().showMessage("Ready - No instrument file selected") # type: ignore
        
    def create_file_panel(self) -> QWidget:
        """Create the file selection panel"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        # File selection group
        file_group = QGroupBox("Instrument File (sInstrInfIn)")
        file_layout = QVBoxLayout(file_group)
        
        # Current file display
        current_file_layout = QHBoxLayout()
        current_file_layout.addWidget(QLabel("Selected File:"))
        
        self.file_display = QLineEdit()
        self.file_display.setReadOnly(True)
        self.file_display.setPlaceholderText("No file selected")
        current_file_layout.addWidget(self.file_display)
        
        file_layout.addLayout(current_file_layout)
        
        # Button layout
        button_layout = QHBoxLayout()
        
        # Select file button
        select_btn = QPushButton("Select Instrument File")
        select_btn.clicked.connect(self.select_instrument_file)
        button_layout.addWidget(select_btn)
        
        # Clear button
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self.clear_file)
        button_layout.addWidget(clear_btn)
        
        file_layout.addLayout(button_layout)
        
        # Directory input
        dir_layout = QHBoxLayout()
        dir_layout.addWidget(QLabel("Working Directory:"))
        self.dir_input = QLineEdit(self.last_directory)
        dir_layout.addWidget(self.dir_input)
        
        browse_dir_btn = QPushButton("Browse")
        browse_dir_btn.clicked.connect(self.browse_directory)
        dir_layout.addWidget(browse_dir_btn)
        
        file_layout.addLayout(dir_layout)
        
        layout.addWidget(file_group)
        
        # Export button
        export_btn = QPushButton("Export File Path")
        export_btn.clicked.connect(self.export_file_path)
        layout.addWidget(export_btn)
        
        return panel
        
    def create_info_panel(self) -> QWidget:
        """Create the file information panel"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        # File info group
        info_group = QGroupBox("File Information")
        info_layout = QVBoxLayout(info_group)
        
        # Info display
        self.info_display = QTextEdit()
        self.info_display.setReadOnly(True)
        self.info_display.setMaximumHeight(120)
        self.info_display.setPlainText("No file selected")
        info_layout.addWidget(self.info_display)
        
        layout.addWidget(info_group)
        
        return panel
        
    def select_instrument_file(self):
        """Select an instrument file"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Instrument File",
            self.dir_input.text() or self.last_directory,
            "Instrument Files (*.inf);;All Files (*)"
        )
        
        if file_path:
            self.set_instrument_file(file_path)
            self.last_directory = os.path.dirname(file_path)
            self.dir_input.setText(self.last_directory)
            
    def set_instrument_file(self, file_path: str):
        """Set the instrument file and update display"""
        self.instrument_file_path = file_path
        
        # Update file display
        self.file_display.setText(file_path)
        
        # Update file info
        self.update_file_info()
        
        # Update status
        self.update_status()
        
    def update_file_info(self):
        """Update the file information display"""
        if not self.instrument_file_path:
            self.info_display.setPlainText("No file selected")
            return
            
        file_path = self.instrument_file_path
        
        # Get file information
        info_parts = []
        info_parts.append(f"File: {os.path.basename(file_path)}")
        info_parts.append(f"Directory: {os.path.dirname(file_path)}")
        
        if os.path.exists(file_path):
            file_size = os.path.getsize(file_path)
            info_parts.append(f"Size: {file_size:,} bytes")
            
            # Get modification time
            import datetime
            mod_time = os.path.getmtime(file_path)
            mod_date = datetime.datetime.fromtimestamp(mod_time).strftime("%Y-%m-%d %H:%M:%S")
            info_parts.append(f"Modified: {mod_date}")
            
            info_parts.append("✅ File exists and is accessible")
        else:
            info_parts.append("❌ File not found")
        
        self.info_display.setPlainText("\n".join(info_parts))
        
    def clear_file(self):
        """Clear the selected file"""
        self.instrument_file_path = None
        self.file_display.clear()
        self.file_display.setPlaceholderText("No file selected")
        self.info_display.setPlainText("No file selected")
        self.update_status()
        
    def browse_directory(self):
        """Browse for working directory"""
        directory = QFileDialog.getExistingDirectory(
            self,
            "Select Working Directory",
            self.dir_input.text() or self.last_directory
        )
        if directory:
            self.dir_input.setText(directory)
            self.last_directory = directory
            
    def update_status(self):
        """Update status bar"""
        if self.instrument_file_path:
            file_name = os.path.basename(self.instrument_file_path)
            if os.path.exists(self.instrument_file_path):
                self.statusBar().showMessage(f"✅ Instrument file: {file_name}") # type: ignore
            else:
                self.statusBar().showMessage(f"❌ File not found: {file_name}") # type: ignore
        else:
            self.statusBar().showMessage("Ready - No instrument file selected") # type: ignore
        
    def export_file_path(self):
        """Export the file path to JSON and close the application"""
        if not self.instrument_file_path:
            QMessageBox.information(self, "Export", "No file to export")
            return
            
        export_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Instrument File Path",
            os.path.join(self.last_directory, "instrument_file.json"),
            "JSON Files (*.json);;All Files (*)"
        )
        
        if export_path:
            try:
                export_data = {
                    "instrument_file": self.instrument_file_path,
                    "file_name": os.path.basename(self.instrument_file_path),
                    "directory": os.path.dirname(self.instrument_file_path),
                    "exists": os.path.exists(self.instrument_file_path)
                }
                
                with open(export_path, 'w') as f:
                    json.dump(export_data, f, indent=2)
                QMessageBox.information(self, "Export", f"Instrument file path exported to {export_path}")
                # Close the application after successful export
                self.close()
            except Exception as e:
                QMessageBox.critical(self, "Export Error", f"Failed to export: {str(e)}")


def main():
    """Main application entry point"""
    app = QApplication(sys.argv)
    app.setApplicationName("Instrument File Manager")
    app.setOrganizationName("Vitess Tools")
    
    # Create and show main window
    window = InstrumentFileManager()
    window.show()
    
    # Run application
    sys.exit(app.exec())


if __name__ == "__main__":
    main()