from PyQt5.QtWidgets import QWidget, QPushButton, QVBoxLayout, QRadioButton
from PyQt5.QtCore import QTimer, pyqtSignal


class ZControlWidget(QWidget):
    # send signal to main window when moving
    stage_moved = pyqtSignal(str, float)  # stage_name, delta z
    def __init__(self, controller, statusbar):
        super().__init__()

        self.controller = controller
        self.status = statusbar

        self.step = 0.001  # mm
        self.direction = 0

        # delay before continuous motion starts
        self.hold_delay = 500   # ms
        self.repeat_interval = 200

        self.hold_timer = QTimer(self)
        self.hold_timer.setSingleShot(True)
        self.hold_timer.timeout.connect(self.start_repeat)

        self.repeat_timer = QTimer(self)
        self.repeat_timer.timeout.connect(self.do_move)

        layout = QVBoxLayout()

        self.up_btn = QPushButton("↑")
        self.stop_btn = QPushButton("STOP")
        self.down_btn = QPushButton("↓")

        self.stop_btn.setStyleSheet("background-color:#8b0000; font-weight:bold")

        self.labjack = QRadioButton("Linear stage")
        self.piezo = QRadioButton("Piezo (N steps = stepsize x 10)")
        self.labjack.setChecked(True)

        layout.addWidget(self.up_btn)
        layout.addWidget(self.stop_btn)
        layout.addWidget(self.down_btn)
        layout.addWidget(self.labjack)
        layout.addWidget(self.piezo)

        self.setLayout(layout)

        # button signals
        self.up_btn.pressed.connect(lambda: self.button_pressed(+1))
        self.down_btn.pressed.connect(lambda: self.button_pressed(-1))
        self.up_btn.released.connect(self.button_released)
        self.down_btn.released.connect(self.button_released)
        self.stop_btn.clicked.connect(self.stop_move)

    # ------------------------------------------------
    # Button handling
    # ------------------------------------------------
    def button_pressed(self, direction):
        self.direction = direction
        self.hold_timer.start(self.hold_delay)

    def button_released(self):
        # if hold timer still running → single step
        if self.hold_timer.isActive():
            self.hold_timer.stop()
            self.do_move()
        self.repeat_timer.stop()

    def start_repeat(self):
        self.repeat_timer.start(self.repeat_interval)

    def stop_move(self):
        self.hold_timer.stop()
        self.repeat_timer.stop()
        self.controller.stop_axes()

    # ------------------------------------------------
    # Motion command
    # ------------------------------------------------
    def do_move(self):
        dz = self.direction * self.step
        if self.labjack.isChecked():
            self.status.showMessage(f"Moving Z stage by {dz*1e3:.1f} µm...", 1000)
            self.controller.move_z_step(dz)
            self.stage_moved.emit("Z Stage", dz)
        else:
            steps = dz * 1e3 * 10 # mm -> um, then x 10 for n in steps
            print(f"calculated steps n={steps}")
            self.status.showMessage(f"Moving Piezo stage by {steps:.0f} steps...", 1000)
            self.controller.move_piezo_step(steps)
            self.stage_moved.emit("Piezo", steps)
