"""
file_save.py
GUI for selecting save location and filename for neutron simulation output
"""

import os
import sys
from typing import Optional
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QLineEdit, QPushButton, QFileDialog, QMessageBox, QGroupBox, QTextEdit
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont


class FileSaveManager(QMainWindow):
    """
    GUI widget for selecting save location and filename for neutron simulation output.
    Provides directory selection and filename entry functionality.
    """
    
    # Signal emitted when save path is confirmed
    save_path_selected = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.save_file_path: Optional[str] = None
        self.last_directory = os.path.expanduser("~")
        
        # Apply monochrome style
        self.apply_monochrome_style()
        
        # Initialize UI
        self.setup_ui()
        self.setup_connections()
    
    def apply_monochrome_style(self):
        """Apply monochrome color scheme matching the FileListManager"""
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
        QPushButton:disabled {
            background-color: #f0f0f0;
            color: #9e9e9e;
            border-color: #e0e0e0;
        }
        QLineEdit {
            background-color: #ffffff;
            border: 1px solid #bdbdbd;
            border-radius: 4px;
            padding: 6px;
            font-family: 'Consolas', monospace;
        }
        QLineEdit:read-only {
            background-color: #f0f0f0;
            color: #666666;
        }
        QTextEdit {
            background-color: #ffffff;
            border: 1px solid #bdbdbd;
            border-radius: 4px;
            padding: 6px;
            font-family: 'Consolas', monospace;
        }
        QTextEdit:read-only {
            background-color: #f9f9f9;
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
        """Set up the user interface"""
        self.setWindowTitle("Vitess AI Agent - Save Output File")
        self.setGeometry(100, 100, 800, 500)
        self.setMinimumSize(600, 400)
        
        
        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Main layout
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(15, 15, 15, 15)
        
        # Title
        title_label = QLabel("Writeout Module -- Output File Manager")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(title_label)
        
        # Directory selection group
        dir_group = QGroupBox("Select Output Directory")
        dir_layout = QVBoxLayout(dir_group)
        
        # Directory selection
        dir_select_layout = QHBoxLayout()
        dir_select_layout.addWidget(QLabel("Directory:"))
        self.dir_path_edit = QLineEdit()
        self.dir_path_edit.setPlaceholderText("Choose directory where output file will be saved...")
        self.dir_path_edit.setText(self.last_directory)
        dir_select_layout.addWidget(self.dir_path_edit)
        
        self.browse_dir_btn = QPushButton("Browse")
        self.browse_dir_btn.setMinimumWidth(80)
        dir_select_layout.addWidget(self.browse_dir_btn)
        
        dir_layout.addLayout(dir_select_layout)
        main_layout.addWidget(dir_group)
        
        # Filename entry group
        file_group = QGroupBox("Output File Configuration (sOutFileName)")
        file_layout = QVBoxLayout(file_group)
        
        # Filename entry
        filename_layout = QHBoxLayout()
        filename_layout.addWidget(QLabel("Filename:"))
        self.filename_edit = QLineEdit()
        self.filename_edit.setPlaceholderText("Enter filename (e.g., neutron_output.out)")
        self.filename_edit.setText("neutron_output.out")  # Default filename
        filename_layout.addWidget(self.filename_edit)
        
        file_layout.addLayout(filename_layout)
        
        # Full path display
        fullpath_layout = QHBoxLayout()
        fullpath_layout.addWidget(QLabel("Full path:"))
        self.fullpath_display = QLineEdit()
        self.fullpath_display.setReadOnly(True)
        fullpath_layout.addWidget(self.fullpath_display)
        
        file_layout.addLayout(fullpath_layout)
        main_layout.addWidget(file_group)
        
        # Info text area
        info_group = QGroupBox("Status Information")
        info_layout = QVBoxLayout(info_group)
        
        self.info_text = QTextEdit()
        self.info_text.setMaximumHeight(120)
        self.info_text.setReadOnly(True)
        self.info_text.setText(
            "1. Select or enter the directory where you want to save the output file.\n"
            "2. Enter the desired filename in the text field.\n"
            "3. Click 'Confirm Save Location' to finalize your selection."
        )
        
        info_layout.addWidget(self.info_text)
        main_layout.addWidget(info_group)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self.confirm_btn = QPushButton("Confirm Save Location")
        self.confirm_btn.setMinimumWidth(150)
        button_layout.addWidget(self.confirm_btn)
        
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setMinimumWidth(100)
        button_layout.addWidget(self.cancel_btn)
        
        button_layout.addStretch()
        main_layout.addLayout(button_layout)
        
        # Status bar
        self.statusBar().showMessage("Ready - Enter save location and filename")
        
        # Update initial state
        self.update_full_path()
        self.update_info_text()
    
    def setup_connections(self):
        """Set up signal-slot connections"""
        self.browse_dir_btn.clicked.connect(self.browse_directory)
        self.dir_path_edit.textChanged.connect(self.update_full_path)
        self.filename_edit.textChanged.connect(self.update_full_path)
        self.confirm_btn.clicked.connect(self.confirm_save_location)
        self.cancel_btn.clicked.connect(self.cancel_selection)
    
    def browse_directory(self):
        """Open directory selection dialog"""
        directory = QFileDialog.getExistingDirectory(
            self,
            "Select Output Directory",
            self.dir_path_edit.text() or self.last_directory,
            QFileDialog.Option.ShowDirsOnly | QFileDialog.Option.DontResolveSymlinks
        )
        
        if directory:
            self.dir_path_edit.setText(directory)
            self.last_directory = directory
            self.update_full_path()
            self.update_info_text()
            self.update_status()
    
    def update_full_path(self):
        """Update the full path display"""
        directory = self.dir_path_edit.text().strip()
        filename = self.filename_edit.text().strip()
        
        if directory and filename:
            full_path = os.path.join(directory, filename)
            self.fullpath_display.setText(full_path)
            self.confirm_btn.setEnabled(True)
        else:
            self.fullpath_display.setText("")
            self.confirm_btn.setEnabled(False)
        
        self.update_info_text()
        self.update_status()
    
    def update_status(self):
        """Update status bar"""
        directory = self.dir_path_edit.text().strip()
        filename = self.filename_edit.text().strip()
        
        if not directory:
            self.statusBar().showMessage("Please select or enter a directory")
        elif not filename:
            self.statusBar().showMessage("Please enter a filename")
        else:
            full_path = os.path.join(directory, filename)
            if os.path.exists(full_path):
                self.statusBar().showMessage("Ready - File exists and will be overwritten")
            else:
                self.statusBar().showMessage("Ready - New file will be created")
    
    def update_info_text(self):
        """Update the information text based on current selection"""
        directory = self.dir_path_edit.text().strip()
        filename = self.filename_edit.text().strip()
        
        if not directory:
            self.info_text.setText(
                "Please select or enter a directory path where the output file will be saved."
            )
            return
        
        if not filename:
            self.info_text.setText(
                "Please enter a filename for the output file."
            )
            return
        
        full_path = os.path.join(directory, filename)
        
        info_parts = []
        
        # Check if directory exists and is writable
        if os.path.exists(directory):
            if os.access(directory, os.W_OK):
                info_parts.append("✅ Directory exists and is writable.")
            else:
                info_parts.append("❌ Directory exists but is not writable.")
        else:
            info_parts.append("📁 Directory will be created if it doesn't exist.")
        
        # Check if file exists
        if os.path.exists(full_path):
            try:
                file_size = os.path.getsize(full_path)
                info_parts.append(f"⚠️ File already exists ({file_size:,} bytes) and will be overwritten.")
            except OSError:
                info_parts.append("⚠️ File already exists and will be overwritten.")
        else:
            info_parts.append("📄 New file will be created.")
        
        info_parts.append(f"📍 Full path: {full_path}")
        
        self.info_text.setText("\n".join(info_parts))
    
    def confirm_save_location(self):
        """Confirm the save location selection"""
        directory = self.dir_path_edit.text().strip()
        filename = self.filename_edit.text().strip()
        
        if not directory or not filename:
            QMessageBox.warning(
                self,
                "Incomplete Selection",
                "Please select both a directory and enter a filename."
            )
            return
        
        full_path = os.path.join(directory, filename)
        
        # Check if directory exists, create if not
        if not os.path.exists(directory):
            try:
                os.makedirs(directory, exist_ok=True)
            except OSError as e:
                QMessageBox.critical(
                    self,
                    "Directory Error",
                    f"Cannot create directory:\n{directory}\n\nError: {str(e)}"
                )
                return
        
        # Check if directory is writable
        if not os.access(directory, os.W_OK):
            QMessageBox.critical(
                self,
                "Permission Error",
                f"Directory is not writable:\n{directory}"
            )
            return
        
        # Check if file exists and ask for confirmation
        if os.path.exists(full_path):
            reply = QMessageBox.question(
                self,
                "File Exists",
                f"The file already exists:\n{full_path}\n\nDo you want to overwrite it?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.No:
                return
        
        # Store the save path and emit signal
        self.save_file_path = full_path
        self.save_path_selected.emit(full_path)
        
        # Update status and close
        self.statusBar().showMessage(f"Save location confirmed: {os.path.basename(full_path)}")
        QMessageBox.information(
            self,
            "Save Location Confirmed",
            f"Output will be saved to:\n{full_path}\n\nClosing file manager..."
        )
        
        self.close()
    
    def cancel_selection(self):
        """Cancel the selection"""
        self.save_file_path = None
        self.statusBar().showMessage("Selection cancelled")
        self.close()
    
    def get_save_path(self) -> Optional[str]:
        """Get the selected save path"""
        return self.save_file_path


def main():
    """Main application entry point"""
    app = QApplication(sys.argv)
    app.setApplicationName("File Save Manager")
    app.setOrganizationName("Vitess Tools")
    
    # Create and show main window
    window = FileSaveManager()
    window.show()
    
    # Run application
    sys.exit(app.exec())


# Example usage and testing
if __name__ == "__main__":
    main()