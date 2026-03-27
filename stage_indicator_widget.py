from PyQt5.QtWidgets import QWidget, QLabel, QHBoxLayout
from PyQt5.QtCore import Qt


class StageIndicatorWidget(QWidget):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller

        layout = QHBoxLayout()
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(0)

        # create a centered container for each label
        self.xy = self._create_centered_label()
        self.z = self._create_centered_label()
        self.piezo = self._create_centered_label()
        self.joy = self._create_centered_label()

        # add stretch before, between, and after to spread them evenly
        layout.addStretch(5)
        layout.addWidget(self.xy, 1)
        layout.addStretch(5)
        layout.addWidget(self.z, 1)
        layout.addStretch(5)
        layout.addWidget(self.piezo, 1)
        layout.addStretch(5)
        layout.addWidget(self.joy, 1)
        layout.addStretch(5)

        self.setLayout(layout)
        self.update_status()

    def _create_centered_label(self):
        label = QLabel()
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return label

    def format(self, name, ok):
        if ok:
            color = "#00c853"
            state = "connected"
        else:
            color = "#ff5252"
            state = "not connected"

        return f'<span style="color:{color}; font-weight:bold">●</span> {name} ({state})'

    def update_status(self):
        self.xy.setText(self.format("XY stage", self.controller.standa.connected))
        self.z.setText(self.format("Z stage", self.controller.zstage.connected))
        self.piezo.setText(self.format("Piezo", self.controller.piezo.connected))
        self.joy.setText(self.format("Joystick", self.controller.joystick.connected))