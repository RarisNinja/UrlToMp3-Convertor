#Every import i need
from PyQt6.QtWidgets import (
    QApplication,
    QLabel,
    QFileDialog,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from PyQt6.QtGui import QIcon
from PyQt6.QtCore import QSize, Qt, QTimer, QThread, pyqtSignal
import sys
import os
import re
from urllib.parse import urlparse
from converter import UrlToMp3Converter

_IPV4_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")

def resource_path(relative_path):
    if getattr(sys, "frozen", False):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)


class ConverterWorker(QThread):
    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, url, output_dir):
        super().__init__()
        self.url = url
        self.output_dir = output_dir

    def run(self):
        try:
            converter = UrlToMp3Converter(output_dir=self.output_dir)
            result = converter.convert(self.url)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


# Subclass QMainWindow to customize your application's main window
class MainWindow(QMainWindow):

    NORMAL_STYLE = """
        QPushButton {
            background-color: #9c9c9c;
            color: white;
            border-radius: 6px;
            padding: 8px;
            font-weight: bold;
        }
        QPushButton:hover {
            background-color: #929292;
        }
        QPushButton:disabled {
            background-color: #cccccc;
            color: #888888;
        }
    """

    CONVERTING_STYLE = """
        QPushButton {
            background: qlineargradient(
                x1:0, y1:0, x2:1, y2:0,
                stop:0 #3a3a3a, stop:1 #6e6e6e
            );
            color: white;
            border-radius: 6px;
            padding: 8px;
            font-weight: bold;
        }
    """

    FINISHED_STYLE = """
        QPushButton {
            background: qlineargradient(
                x1:0, y1:0, x2:1, y2:0,
                stop:0 #2e7d32, stop:1 #66bb6a
            );
            color: white;
            border-radius: 6px;
            padding: 8px;
            font-weight: bold;
        }
    """

    WARNING_STYLE = """
        QPushButton {
            background: qlineargradient(
                x1:0, y1:0, x2:1, y2:0,
                stop:0 #fafd3f, stop:1 #dad863
            );
            color: white;
            border-radius: 6px;
            padding: 8px;
            font-weight: bold;
        }
    """

    ERROR_STYLE = """
        QPushButton {
            background: qlineargradient(
                x1:0, y1:0, x2:1, y2:0,
                stop:0 #7d2e2e, stop:1 #bb6666
            );
            color: white;
            border-radius: 6px;
            padding: 8px;
            font-weight: bold;
        }
    """

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose download folder", self.output_dir)
        if folder:
            self.output_dir = folder
            self.folder_label.setText(f"Saves to: {folder}")

    def _is_valid_url(self, url: str) -> bool:
        # A pasted/typed URL never contains literal whitespace - plain
        # sentences like "this is not a url" do, so bail out immediately.
        if any(ch.isspace() for ch in url):
            return False

        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False

        host = parsed.hostname
        if not host:
            return False

        # A single word like "hello" parses to a "valid" host with no dot,
        # which isn't a real domain. Accept it only if it looks like an
        # actual host: has a dot (youtube.com), is localhost, or is an IP.
        if host == "localhost" or _IPV4_RE.match(host):
            return True
        return "." in host

    def convert_url(self):
        url = self.input.text().strip()
        if not url:
            return

        # Be lenient about a missing scheme (e.g. "youtube.com/watch?v=xyz")
        # rather than treating it as unrecognizable outright.
        if not urlparse(url).scheme:
            url = "https://" + url

        if not self._is_valid_url(url):
            self.show_warning()
            return

        # Enter "converting" state
        self.ConvertButton.setEnabled(False)
        self.ConvertButton.setText("Converting...")
        self.ConvertButton.setStyleSheet(self.CONVERTING_STYLE)
        self.input.setEnabled(False)

        # Run the actual conversion in a background thread so the UI
        # stays responsive and can actually show the state above.
        self.worker = ConverterWorker(url, self.output_dir)
        self.worker.finished.connect(self.on_conversion_finished)
        self.worker.error.connect(self.on_conversion_error)
        self.worker.start()

    def on_conversion_finished(self, result):
        print(result)
        self.input.clear() 
        self.ConvertButton.setText("Finished!")
        self.ConvertButton.setStyleSheet(self.FINISHED_STYLE)
        QTimer.singleShot(2000, self.reset_button)

    def on_conversion_error(self, error_message):
        print(f"Error: {error_message}")
        self.input.clear()
        self.ConvertButton.setText("Conversion failed")
        self.ConvertButton.setStyleSheet(self.ERROR_STYLE)
        QTimer.singleShot(2000, self.reset_button)

    def show_warning(self):
        self.ConvertButton.setEnabled(False)
        self.ConvertButton.setText("Paste a correct or functionable URL")
        self.ConvertButton.setStyleSheet(self.WARNING_STYLE)
        self.input.clear()
        QTimer.singleShot(2000, self.reset_button)

    def reset_button(self):
        self.input.setEnabled(True)
        self.input.clear() 
        self.ConvertButton.setText("Convert!")
        self.ConvertButton.setStyleSheet(self.NORMAL_STYLE)
    
    def on_text_changed(self, text):
        self.ConvertButton.setEnabled(bool(text.strip()))

    def __init__(self):
        super().__init__()

        # Output directory
        self.output_dir = "downloads"
        # Title for the window
        self.setWindowTitle("UrlToMp3")
        #The size of the Window
        self.setFixedSize(QSize(800, 260))
        # Window Icon
        self.setWindowIcon(QIcon(resource_path("UTM3 icon.ico")))

        # Create a Layout
        layout = QVBoxLayout()

        # Input Box
        labelURL = QLabel()
        self.input = QLineEdit()
        self.folder_label = QLabel(f"Currently saves to: {self.output_dir}")
        self.chooseFolderButton = QPushButton("Choose Folder")
        self.chooseFolderButton.clicked.connect(self.choose_folder)
        self.input.textChanged.connect(self.on_text_changed)
        self.input.setPlaceholderText("Paste any url")

        # Convert button
        self.ConvertButton = QPushButton("Convert!")
        self.ConvertButton.setEnabled(False)
        self.ConvertButton.setStyleSheet(self.NORMAL_STYLE)
        self.ConvertButton.clicked.connect(self.convert_url)

        # Text Title
        label = QLabel("Url To Mp3 Converter!")
        font = label.font()
        font.setBold(True)
        font.setPointSize(30)
        label.setFont(font)
        label.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop
        )

        # Text Description
        label2 = QLabel("This is a app where you can convert any url and you get the song and the cover-art for it")
        font2 = label2.font()
        font2.setPointSize(14)
        label2.setFont(font2)
        label2.setAlignment(
            Qt.AlignmentFlag.AlignHCenter
        )

        # Version Label
        version_desc = QLabel("v.0.1")
        vfont = version_desc.font()
        vfont.setItalic(True)
        vfont.setPointSize(10)
        version_desc.setFont(vfont)
        version_desc.setAlignment(
            Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight
        )

        # Add labels (and other interactives) to the layout
        layout.addWidget(label)
        layout.addWidget(label2)
        layout.addWidget(self.input)
        layout.addWidget(labelURL)

        layout.addWidget(self.ConvertButton)

        layout.addWidget(self.chooseFolderButton)
        layout.addWidget(self.folder_label)

        # THIS STAYS AT THE BOTTOM AT ALL TIMES, NO MATTER THE COST!
        layout.addWidget(version_desc)

        #Margin between the two text
        layout.setSpacing(5)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Create central widget since theres more than one labels
        container = QWidget()
        container.setLayout(layout)

        self.setCentralWidget(container)

        self.worker = None
        self.show()

# Make a variable to make it easier on myself
app = QApplication(sys.argv)

# Refrencing the window
window = MainWindow()
window.show()

# Start the event loop
app.exec()