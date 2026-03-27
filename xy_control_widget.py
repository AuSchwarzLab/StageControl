from PyQt5.QtWidgets import QWidget, QPushButton, QGridLayout
from PyQt5.QtCore import QTimer, pyqtSignal


class XYControlWidget(QWidget):
    # send signal to main window when moving
    stage_moved = pyqtSignal(str, float, float)  # stage_name, x, y
    def __init__(self, controller, statusbar):
        super().__init__()

        self.controller = controller
        self.status = statusbar

        # step size in millimeters
        self.step = 0.001  # default = 1 µm

        # timing
        self.repeat_interval = 100   # ms between repeated steps
        self.hold_delay = 500        # ms before repeat starts

        # direction state
        self.dx = 0
        self.dy = 0

        # timer for continuous movement
        self.repeat_timer = QTimer()
        self.repeat_timer.timeout.connect(self.do_move)

        # timer for detecting a held button
        self.hold_timer = QTimer()
        self.hold_timer.setSingleShot(True)
        self.hold_timer.timeout.connect(self.start_repeat)

        layout = QGridLayout()

        up = QPushButton("↑")
        down = QPushButton("↓")
        left = QPushButton("←")
        right = QPushButton("→")
        stop = QPushButton("STOP")
        stop.setStyleSheet("background-color:#8b0000; font-weight:bold")
        layout.addWidget(up, 0, 1)
        layout.addWidget(left, 1, 0)
        layout.addWidget(stop, 1, 1)
        layout.addWidget(right, 1, 2)
        layout.addWidget(down, 2, 1)

        self.setLayout(layout)

        # connect buttons
        self.connect_button(up, 0, 1)
        self.connect_button(down, 0, -1)
        self.connect_button(left, -1, 0)
        self.connect_button(right, 1, 0)

        stop.clicked.connect(self.stop_move)

    def connect_button(self, button, dx, dy):
        button.pressed.connect(lambda: self.start_move(dx, dy))
        button.released.connect(self.stop_move)

    def start_move(self, dx, dy):
        self.dx = dx
        self.dy = dy
        # immediate step
        self.do_move()
        # start hold detection
        self.hold_timer.start(self.hold_delay)

    def start_repeat(self):
        self.repeat_timer.start(self.repeat_interval)

    def stop_move(self):
        self.hold_timer.stop()
        self.repeat_timer.stop()
        self.controller.stop_axes()

    def do_move(self):
        x_travel = self.dx * self.step
        y_travel = self.dy * self.step
        if abs(x_travel) >= abs(y_travel):
            val = x_travel
            name = "X"
        else:
            val = y_travel
            name = "Y"
        self.status.showMessage(f"Moving {name} stage by {val*1e3:.1f} µm...", 1000)
        self.stage_moved.emit("XY Stage", x_travel, y_travel)
        self.controller.move_xy_step(x_travel, y_travel)
