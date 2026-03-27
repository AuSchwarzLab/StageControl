from PyQt5.QtWidgets import QDialog, QMessageBox, QVBoxLayout, QListWidget, QHBoxLayout, QPushButton
import glob
import os

class PositionManager(QDialog):
    """Helper class for managing xyz stage positions"""
    POS_DIR = "./positions"

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle("Manage Positions")

        layout = QVBoxLayout(self)

        self.list = QListWidget()
        layout.addWidget(self.list)

        btn_layout = QHBoxLayout()
        delete_btn = QPushButton("Delete")
        close_btn = QPushButton("Close")

        btn_layout.addWidget(close_btn)
        btn_layout.addWidget(delete_btn)
        layout.addLayout(btn_layout)

        delete_btn.clicked.connect(self.delete_selected)
        close_btn.clicked.connect(self.accept)

        self.update_list()

    # -----------------------------
    # reusable position functions
    # -----------------------------
    @classmethod
    def list_positions(cls):
        files = glob.glob(f"{cls.POS_DIR}/position_*.txt")
        names = []
        for f in files:
            name = os.path.basename(f)
            name = name.replace("position_", "").replace(".txt", "")
            names.append(name)
        return sorted(names)

    @classmethod
    def save_position(cls, name, x, y, z):
        os.makedirs(cls.POS_DIR, exist_ok=True)
        filename = f"{cls.POS_DIR}/position_{name}.txt"
        with open(filename, "w") as f:
            f.write(f"{x} {y} {z}")

    @classmethod
    def load_position(cls, name):
        filename = f"{cls.POS_DIR}/position_{name}.txt"
        with open(filename) as f:
            x, y, z = map(float, f.read().split())
        return x, y, z

    @classmethod
    def delete_position(cls, name):
        filename = f"{cls.POS_DIR}/position_{name}.txt"
        os.remove(filename)

    # -----------------------------
    # dialog-specific UI functions
    # -----------------------------
    def update_list(self):
        self.list.clear()
        for name in self.list_positions():
            self.list.addItem(name)

    def delete_selected(self):
        item = self.list.currentItem()
        if not item:
            return
        name = item.text()
        try:
            self.delete_position(name)
        except Exception as e:
            QMessageBox.warning(self, "Error", str(e))
            return

        self.update_list()