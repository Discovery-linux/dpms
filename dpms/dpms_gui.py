import os
import sys
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QLineEdit, QPushButton, QLabel, QRadioButton, QGroupBox,
    QFileDialog, QTextEdit, QStatusBar
)
from PyQt5.QtCore import QThread, pyqtSignal, QObject
from PyQt5.QtGui import QIcon
 
if __package__ is None:
    from dpms_core import (
        make_tar, download_file, DPMSCoreError, InvalidSourceError,
        UnsupportedCompressionError, SubprocessError, NetworkError
    )
else:
    from .dpms_core import (
        make_tar, download_file, DPMSCoreError, InvalidSourceError,
        UnsupportedCompressionError, SubprocessError, NetworkError
    )


class CompressionWorker(QObject):
    finished = pyqtSignal(str)
    error = pyqtSignal(Exception)

    def __init__(self, source_path, output_path, compression_type, verbose):
        super().__init__()
        self.source_path = source_path
        self.output_path = output_path
        self.compression_type = compression_type
        self.verbose = verbose

    def run(self):
        try:
            make_tar(self.source_path, self.output_path, self.compression_type, verbose=self.verbose)
            self.finished.emit("Compression completed successfully!")
        except Exception as e:
            self.error.emit(e)


class DownloadWorker(QObject):
    finished = pyqtSignal(str)
    error = pyqtSignal(Exception)

    def __init__(self, url, output_path, verbose):
        super().__init__()
        self.url = url
        self.output_path = output_path
        self.verbose = verbose

    def run(self):
        try:
            download_file(self.url, self.output_path, self.verbose)
            self.finished.emit("Download completed successfully!")
        except Exception as e:
            self.error.emit(e)


class DPMSShell(QMainWindow):
    def __init__(self, verbose=False):
        super().__init__()
        self.verbose = verbose
        self.setWindowTitle("DPMS GUI")
        self.setGeometry(100, 100, 600, 400)
        self.setWindowIcon(QIcon.fromTheme("utilities-terminal"))

        self.main_widget = QWidget()
        self.setCentralWidget(self.main_widget)
        self.main_layout = QVBoxLayout()
        self.main_widget.setLayout(self.main_layout)

        self.tabs = QTabWidget()
        self.main_layout.addWidget(self.tabs)

        self.create_convert_tab()
        self.create_download_tab()
        self.create_log_area()

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready.")

    def create_log_area(self):
        log_box = QGroupBox("Status & Log")
        log_layout = QVBoxLayout()
        log_box.setLayout(log_layout)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        log_layout.addWidget(self.log_text)
        self.main_layout.addWidget(log_box)

    def log_message(self, message, color="black"):
        self.log_text.append(f"<span style='color:{color};'>{message}</span>")
        self.status_bar.showMessage(message)

    def create_convert_tab(self):
        convert_tab = QWidget()
        layout = QVBoxLayout()
        convert_tab.setLayout(layout)
        self.tabs.addTab(convert_tab, "Convert")

        source_layout = QHBoxLayout()
        source_label = QLabel("Source Path:")
        self.source_input = QLineEdit()
        source_button = QPushButton("Browse...")
        source_button.clicked.connect(self.select_source_path)
        source_layout.addWidget(source_label)
        source_layout.addWidget(self.source_input)
        source_layout.addWidget(source_button)
        layout.addLayout(source_layout)

        output_layout = QHBoxLayout()
        output_label = QLabel("Output Filename:")
        self.output_input = QLineEdit()
        output_layout.addWidget(output_label)
        output_layout.addWidget(self.output_input)
        layout.addLayout(output_layout)

        output_path_layout = QHBoxLayout()
        output_path_label = QLabel("Output Path:")
        self.output_path_input = QLineEdit()
        output_path_button = QPushButton("Browse...")
        output_path_button.clicked.connect(self.select_output_path)
        output_path_layout.addWidget(output_path_label)
        output_path_layout.addWidget(self.output_path_input)
        output_path_layout.addWidget(output_path_button)
        layout.addLayout(output_path_layout)

        compression_group = QGroupBox("Compression Type")
        compression_layout = QHBoxLayout()
        compression_group.setLayout(compression_layout)
        self.gz_radio = QRadioButton("gzip (.tar.gz)")
        self.xz_radio = QRadioButton("xz (.tar.xz)")
        self.gz_radio.setChecked(True)
        compression_layout.addWidget(self.gz_radio)
        compression_layout.addWidget(self.xz_radio)
        layout.addWidget(compression_group)

        convert_button = QPushButton("Compress")
        convert_button.clicked.connect(self.start_compression)
        layout.addWidget(convert_button)

    def create_download_tab(self):
        download_tab = QWidget()
        layout = QVBoxLayout()
        download_tab.setLayout(layout)
        self.tabs.addTab(download_tab, "Download")

        url_layout = QHBoxLayout()
        url_label = QLabel("URL:")
        self.url_input = QLineEdit()
        url_layout.addWidget(url_label)
        url_layout.addWidget(self.url_input)
        layout.addLayout(url_layout)

        output_path_layout = QHBoxLayout()
        output_path_label = QLabel("Output Path:")
        self.output_path_input_download = QLineEdit()
        output_path_button = QPushButton("Browse...")
        output_path_button.clicked.connect(self.select_output_path_download)
        output_path_layout.addWidget(output_path_label)
        output_path_layout.addWidget(self.output_path_input_download)
        output_path_layout.addWidget(output_path_button)
        layout.addLayout(output_path_layout)

        download_button = QPushButton("Download")
        download_button.clicked.connect(self.start_download)
        layout.addWidget(download_button)

    def select_source_path(self):
        path = QFileDialog.getExistingDirectory(self, "Select Directory to Compress")
        if path:
            self.source_input.setText(path)

    def select_output_path(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save File As", "", "All Files (*)")
        if path:
            self.output_path_input.setText(path)

    def select_output_path_download(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save File As", "", "All Files (*)")
        if path:
            self.output_path_input_download.setText(path)

    def start_compression(self):
        source_path = self.source_input.text()
        output_filename = self.output_input.text()
        output_path = self.output_path_input.text()
        compression_type = 'gz' if self.gz_radio.isChecked() else 'xz'

        if not source_path or not output_filename or not output_path:
            self.log_message("Error: Source path, output filename, and output path are required.", "red")
            return

        full_output_path = os.path.join(output_path, output_filename)

        self.log_message(f"Starting compression of '{source_path}'...", "blue")
        self.status_bar.showMessage("Compressing...")

        self.thread = QThread()
        self.worker = CompressionWorker(source_path, full_output_path, compression_type, self.verbose)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.on_compression_finished)
        self.worker.error.connect(self.on_compression_error)
        self.thread.start()

    def on_compression_finished(self, message):
        self.log_message(message, "green")
        self.status_bar.showMessage("Ready.")
        self.thread.quit()
        self.thread.wait()

    def on_compression_error(self, e):
        self.log_message(f"Error: {e}", "red")
        self.status_bar.showMessage("Operation failed.")
        self.thread.quit()
        self.thread.wait()

    def start_download(self):
        url = self.url_input.text()
        output_path = self.output_path_input_download.text()

        if not url or not output_path:
            self.log_message("Error: URL and output path are required.", "red")
            return

        self.log_message(f"Starting download from '{url}'...", "blue")
        self.status_bar.showMessage("Downloading...")

        self.thread = QThread()
        self.worker = DownloadWorker(url, output_path, self.verbose)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.on_download_finished)
        self.worker.error.connect(self.on_download_error)
        self.thread.start()

    def on_download_finished(self, message):
        self.log_message(message, "green")
        self.status_bar.showMessage("Ready.")
        self.thread.quit()
        self.thread.wait()

    def on_download_error(self, e):
        self.log_message(f"Error: {e}", "red")
        self.status_bar.showMessage("Operation failed.")
        self.thread.quit()
        self.thread.wait()


def main():
    app = QApplication(sys.argv)
    window = DPMSShell()
    window.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
