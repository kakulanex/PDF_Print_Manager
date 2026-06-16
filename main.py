import os
import sys
import time
import subprocess
import sqlite3
import requests
import webbrowser

from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QFileDialog, QTableWidget, QTableWidgetItem,
    QLabel, QProgressBar, QComboBox, QLineEdit, QMessageBox
)

from PySide6.QtCore import Qt, QThread, Signal

import win32print


# =========================
# VERSION + UPDATE SYSTEM
# =========================
CURRENT_VERSION = "1.0.0"

UPDATE_URL = "https://raw.githubusercontent.com/kakulanex/PDF_Print_Manager/main/update.json"


def check_update():
    try:
        data = requests.get(UPDATE_URL, timeout=10).json()

        latest_version = data.get("version")
        download_url = data.get("url")

        if latest_version and latest_version != CURRENT_VERSION:
            return download_url, latest_version

    except Exception as e:
        print("Update check failed:", e)

    return None, None


def prompt_update(parent=None):
    download_url, latest_version = check_update()

    if download_url:
        reply = QMessageBox.question(
            parent,
            "Update Available",
            f"A new version ({latest_version}) is available.\n\nDo you want to download it?",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            webbrowser.open(download_url)


# =========================
# SAFE BASE PATH (PORTABLE + EXE)
# =========================
def base_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


BASE_DIR = base_dir()

SUMATRA = os.path.join(BASE_DIR, "SumatraPDF", "SumatraPDF.exe")
LOG_FILE = os.path.join(BASE_DIR, "print_log.txt")
DB_FILE = os.path.join(BASE_DIR, "users.db")


# =========================
# DATABASE (LOGIN SIMPLE)
# =========================
conn = sqlite3.connect(DB_FILE)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS users (
    username admin,
    password password
)
""")

cur.execute("SELECT * FROM users")
if not cur.fetchone():
    cur.execute("INSERT INTO users VALUES ('admin','admin')")
conn.commit()


# =========================
# PRINT THREAD
# =========================
class PrintThread(QThread):
    progress = Signal(int)
    status = Signal(str)
    finished = Signal()

    def __init__(self, files, printer, copies):
        super().__init__()
        self.files = files
        self.printer = printer
        self.copies = copies
        self.running = True
        self.paused = False

    def run(self):
        total = len(self.files)

        for i, file in enumerate(self.files):
            if not self.running:
                break

            while self.paused:
                time.sleep(0.3)

            success = False

            for attempt in range(3):
                try:
                    for _ in range(self.copies):
                        subprocess.run([
                            SUMATRA,
                            "-print-to",
                            self.printer,
                            file
                        ], check=True)

                    success = True
                    break

                except Exception:
                    time.sleep(2)

            name = os.path.basename(file)

            if success:
                self.status.emit(f"Printed: {name}")
                with open(LOG_FILE, "a") as f:
                    f.write(f"SUCCESS: {file}\n")
            else:
                self.status.emit(f"FAILED: {name}")
                with open(LOG_FILE, "a") as f:
                    f.write(f"FAILED: {file}\n")

            self.progress.emit(int(((i + 1) / total) * 100))
            time.sleep(1)

        self.finished.emit()


# =========================
# MAIN APP
# =========================
class App(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("PDF Print Manager PRO (Portable)")
        self.setGeometry(200, 100, 900, 600)

        self.files = []
        self.thread = None

        self.init_ui()

        # ✅ RUN UPDATE CHECK ON STARTUP
        prompt_update(self)

    def init_ui(self):
        layout = QVBoxLayout()

        top = QHBoxLayout()

        self.folder_btn = QPushButton("Select Folder")
        self.folder_btn.clicked.connect(self.load_folder)

        self.printer_box = QComboBox()
        self.printer_box.addItems(self.get_printers())

        self.copies = QLineEdit("1")
        self.copies.setFixedWidth(50)

        self.start_btn = QPushButton("Start")
        self.pause_btn = QPushButton("Pause/Resume")
        self.cancel_btn = QPushButton("Cancel")

        self.start_btn.clicked.connect(self.start_print)
        self.pause_btn.clicked.connect(self.toggle_pause)
        self.cancel_btn.clicked.connect(self.cancel_print)

        top.addWidget(self.folder_btn)
        top.addWidget(self.printer_box)
        top.addWidget(QLabel("Copies:"))
        top.addWidget(self.copies)
        top.addWidget(self.start_btn)
        top.addWidget(self.pause_btn)
        top.addWidget(self.cancel_btn)

        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["File", "Status"])

        self.progress = QProgressBar()
        self.status = QLabel("Ready")

        layout.addLayout(top)
        layout.addWidget(self.table)
        layout.addWidget(self.progress)
        layout.addWidget(self.status)

        self.setLayout(layout)

        self.setStyleSheet("""
            QWidget { background-color: #1e1e1e; color: white; }
            QPushButton { background-color: #333; padding: 5px; }
            QTableWidget { background-color: #2b2b2b; }
            QLineEdit { background-color: #333; color: white; }
        """)

    def get_printers(self):
        return [p[2] for p in win32print.EnumPrinters(2)]

    def load_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder")

        if folder:
            self.files.clear()

            for root, _, files in os.walk(folder):
                for f in files:
                    if f.lower().endswith(".pdf"):
                        self.files.append(os.path.join(root, f))

            self.files.sort()
            self.populate_table()

    def populate_table(self):
        self.table.setRowCount(len(self.files))

        for i, f in enumerate(self.files):
            self.table.setItem(i, 0, QTableWidgetItem(os.path.basename(f)))
            self.table.setItem(i, 1, QTableWidgetItem("Queued"))

    def start_print(self):
        if not self.files:
            QMessageBox.warning(self, "Error", "No files selected")
            return

        printer = self.printer_box.currentText()
        copies = int(self.copies.text())

        self.thread = PrintThread(self.files, printer, copies)

        self.thread.progress.connect(self.progress.setValue)
        self.thread.status.connect(self.update_status)
        self.thread.finished.connect(self.done)

        self.thread.start()

    def toggle_pause(self):
        if self.thread:
            self.thread.paused = not self.thread.paused

    def cancel_print(self):
        if self.thread:
            self.thread.running = False

    def update_status(self, msg):
        self.status.setText(msg)

    def done(self):
        self.status.setText("Completed ✔")

        import winsound
        winsound.Beep(1200, 500)


# =========================
# RUN APP
# =========================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = App()
    window.show()
    sys.exit(app.exec())
