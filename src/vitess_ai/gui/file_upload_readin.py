"""
Simple File List Manager for Vitess Read-In module 
"""

import sys
import os
import json
from typing import List
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QListWidget, QListWidgetItem, QLineEdit,
    QFileDialog, QMessageBox, QGroupBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

class FileListManager(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Vitess AI Agent")
        self.setGeometry(100, 100, 800, 600)
        self.setMinimumSize(600, 400)
        
        # File list storage
        self.file_paths: List[str] = []
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
        QListWidget {
            background-color: #ffffff;
            border: 1px solid #bdbdbd;
            border-radius: 4px;
            padding: 4px;
            font-family: 'Consolas', monospace;
        }
        QListWidget::item {
            padding: 4px;
            border-bottom: 1px solid #e0e0e0;
        }
        QListWidget::item:selected {
            background-color: #d0d0d0;
            color: #2d2d2d;
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
        title_label = QLabel("Read-in Module -- Input Files Manager")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(title_label)
        
        # File list panel
        file_panel = self.create_file_list_panel()
        main_layout.addWidget(file_panel)
        
        # Status bar
        self.statusBar().showMessage("Ready - No files selected") # type: ignore
        
    def create_file_list_panel(self) -> QWidget:
        """Create the file list management panel"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        # File list group
        file_group = QGroupBox("Input Files (sInputFileName)")
        file_layout = QVBoxLayout(file_group)
        
        # File list widget
        self.file_list = QListWidget()
        self.file_list.setAlternatingRowColors(True)
        file_layout.addWidget(self.file_list)
        
        # Button layout
        button_layout = QHBoxLayout()
        
        # Add files button (multiple files)
        add_files_btn = QPushButton("Add Files")
        add_files_btn.clicked.connect(self.add_files)
        button_layout.addWidget(add_files_btn)
        
        # Remove selected button
        remove_btn = QPushButton("Remove")
        remove_btn.clicked.connect(self.remove_selected_file)
        button_layout.addWidget(remove_btn)
        
        # Clear all button
        clear_btn = QPushButton("Clear All")
        clear_btn.clicked.connect(self.clear_all_files)
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
        export_btn = QPushButton("Export List")
        export_btn.clicked.connect(self.export_file_list)
        layout.addWidget(export_btn)
        
        return panel
        
        
    def add_files(self):
        """Add files to the list (minimum 1, maximum NF_MAX)"""
        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Input Files",
            self.dir_input.text() or self.last_directory,
            "All Files (*);;Data Files (*.dat *.txt *.csv);;Neutron Files (*.dat *.nxs *.h5)"
        )
        
        if file_paths:
            # Check if adding these files would exceed NF_MAX
            total_files = len(self.file_paths) + len(file_paths)
            if total_files > 3:  # NF_MAX
                excess = total_files - 3
                QMessageBox.warning(
                    self, 
                    "Too Many Files", 
                    f"Cannot add all files. Maximum is 3 files total.\n"
                    f"Will add only the first {len(file_paths) - excess} files."
                )
                file_paths = file_paths[:len(file_paths) - excess]
            
            for file_path in file_paths:
                self.add_file_to_list(file_path)
            self.last_directory = os.path.dirname(file_paths[0])
            self.dir_input.setText(self.last_directory)
            
    def add_file_to_list(self, file_path: str):
        """Add a file path to the list"""
        if len(self.file_paths) >= 3:  # NF_MAX
            QMessageBox.warning(self, "Maximum Files", "Cannot add more files. Maximum is 3 files.")
            return
            
        if file_path not in self.file_paths:
            self.file_paths.append(file_path)
            item = QListWidgetItem(file_path)
            item.setToolTip(file_path)  # Show full path on hover
            self.file_list.addItem(item)
            self.update_status()
            
    def remove_selected_file(self):
        """Remove selected file from the list"""
        current_row = self.file_list.currentRow()
        if current_row >= 0:
            self.file_list.takeItem(current_row)
            del self.file_paths[current_row]
            self.update_status()
            
    def clear_all_files(self):
        """Clear all files from the list"""
        self.file_list.clear()
        self.file_paths.clear()
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
        count = len(self.file_paths)
        max_files = 3  # NF_MAX
        if count == 0:
            self.statusBar().showMessage("Ready - No files selected") # type: ignore
        elif count == 1:
            self.statusBar().showMessage(f"1 file selected (max {max_files})") # type: ignore
        else:
            self.statusBar().showMessage(f"{count} files selected (max {max_files})") # type: ignore
        
    def export_file_list(self):
        """Export file list to JSON and close the application"""
        if not self.file_paths:
            QMessageBox.information(self, "Export", "No files to export")
            return
            
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export File List",
            os.path.join(self.last_directory, "file_list.json"),
            "JSON Files (*.json);;All Files (*)"
        )
        
        if file_path:
            try:
                with open(file_path, 'w') as f:
                    json.dump(self.file_paths, f, indent=2)
                QMessageBox.information(self, "Export", f"File list exported to {file_path}")
                # Close the application after successful export
                self.close()
            except Exception as e:
                QMessageBox.critical(self, "Export Error", f"Failed to export: {str(e)}")


def main():
    """Main application entry point"""
    app = QApplication(sys.argv)
    app.setApplicationName("File List Manager")
    app.setOrganizationName("Vitess Tools")
    
    # Create and show main window
    window = FileListManager()
    window.show()
    
    # Run application
    sys.exit(app.exec())


if __name__ == "__main__":
    main()