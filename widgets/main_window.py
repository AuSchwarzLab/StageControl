from PyQt5.QtWidgets import (
    QDialog, QFrame, QMainWindow, QWidget, QLabel, QPushButton, QGridLayout,
    QVBoxLayout, QHBoxLayout, QRadioButton, QButtonGroup, QSizePolicy,
    QGroupBox, QSlider, QMessageBox, QStatusBar, QLineEdit, QComboBox
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt5.QtGui import QDoubleValidator, QPixmap

import re, sys
import os
from widgets.xy_control_widget import XYControlWidget
from widgets.z_control_widget import ZControlWidget
from widgets.stage_indicator_widget import StageIndicatorWidget
from utils.position_manager import PositionManager
from utils.logger import StageControlLogger


class ControllerSignals(QObject):
    event = pyqtSignal(dict)


class MainWindow(QMainWindow):
    def __init__(self, controller):
        super().__init__()
        self.setWindowTitle("Stage Control – Multi Axis System")
        self.log = StageControlLogger()
        self.log.info("Application started")

        self.controller = controller
        #  callbacks
        self.ctrl_signals = ControllerSignals()
        # connect Qt signal to handler
        self.ctrl_signals.event.connect(self.handle_controller_event)
        # connect controller → Qt signal bridge
        self.controller.event_callback = self.ctrl_signals.event.emit

        # check hardware connections
        self.check_hardware_connections()

        self.status = QStatusBar()
        self.setStatusBar(self.status)

        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QVBoxLayout()
        central.setLayout(main_layout)

        # ---------- stage indicators ----------
        main_layout.addWidget(self.build_section_header("Hardware connections"))
        self.stage_indicator = StageIndicatorWidget(controller)
        main_layout.addWidget(self.stage_indicator)

        # ---------- manual control ----------
        main_layout.addWidget(self.build_section_header("Manual control"))
        control_layout = QHBoxLayout()
        self.xy_control = XYControlWidget(controller, self.status)
        control_layout.addWidget(self.xy_control)
        self.z_control = ZControlWidget(controller, self.status)
        control_layout.addWidget(self.z_control)
        main_layout.addLayout(control_layout)
        # connect slots from manual control widgets with logger
        self.xy_control.stage_moved.connect(
            lambda name, x, y: self.log.info(f"Manual move with {name} by x = {x*1e3:.1f} um, y = {y*1e3:.1f} um")
        )
        self.z_control.stage_moved.connect(
            lambda name, dz: self.log.info(
                f"{name} moved by {dz*1e3:.1f} um" if name == "Z Stage" else f"{int(dz)} steps"
            )
        )

        # ---------- step size ----------
        main_layout.addWidget(self.build_section_header("Step size for manual control"))
        self.step_box = self.build_step_box()
        main_layout.addWidget(self.step_box)

        # ---------- position display ----------
        main_layout.addWidget(self.build_section_header("Position readout & limitation"))
        self.pos_box = self.build_position_box()
        main_layout.addWidget(self.pos_box)

        # ---------- save/load ----------
        main_layout.addWidget(self.build_section_header("Save / Go to position"))
        self.save_box = self.build_save_box()
        main_layout.addWidget(self.save_box)

        # ---------- velocity sliders ----------
        main_layout.addWidget(self.build_section_header("Joystick sensitivity"))
        self.vel_box = self.build_velocity_box()
        main_layout.addWidget(self.vel_box)

        # ---------- help button ----------
        main_layout.addWidget(self.build_help_box())

        # timer for position updates
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_positions)
        self.timer.start(200)

        # timer for blinking remote control button
        self.remote_blink_timer = QTimer()
        self.remote_blink_timer.timeout.connect(
            self.remote_blink_step
        )
        self.remote_blink_state = False
        self.remote_blink_counter = 0
        self.install_remote_mode_filters()

        # size of the GUI window
        #self.resize(500, 600)
        self.adjustSize()
        self.setFixedSize(self.size())
        self.raise_()
        self.activateWindow()

        # check if z-stage was homed and show message box
        QTimer.singleShot(0, self.check_zstage_homed)

    # ------------------------------------------------
    # Position display
    # ------------------------------------------------
    def build_position_box(self):
        box = QGroupBox()
        layout = QGridLayout()

        self.x_label = QLabel("---")
        self.y_label = QLabel("---")
        self.z_label = QLabel("---")
        self.p_label = QLabel("---")

        # --- Z limit widgets ---
        self.z_limit_edit = QLineEdit()
        self.z_limit_edit.setPlaceholderText("Enter max z")
        validator = QDoubleValidator(50, 50e3, 5)  # min, max, decimals
        validator.setNotation(QDoubleValidator.StandardNotation)
        self.z_limit_edit.setStyleSheet("""
            QLineEdit:invalid {
                border: 1px solid red;
            }
        """)
        self.z_limit_edit.setValidator(validator)
        self.z_limit_edit.textChanged.connect(self.update_z_limit)

        self.z_limit_btn = QPushButton("Activate Z-limit")
        self.z_limit_btn.setCheckable(True)
        self.z_limit_btn.clicked.connect(self.toggle_z_limit)

        self.z_limit_status = QLabel("")  # feedback text

        # --- layout ---
        layout.addWidget(QLabel("X:"), 0, 0)
        layout.addWidget(self.x_label, 0, 1)

        layout.addWidget(QLabel("Y:"), 1, 0)
        layout.addWidget(self.y_label, 1, 1)

        layout.addWidget(QLabel("Z:"), 2, 0)
        z_controls = QHBoxLayout()
        z_controls.setSpacing(8)
        z_controls.addWidget(self.z_limit_edit)
        z_controls.addWidget(self.z_limit_btn)
        # optional: prevent them from stretching too much
        self.z_limit_edit.setFixedWidth(140)
        self.z_limit_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.z_limit_btn.setFixedWidth(140)
        layout.addWidget(self.z_label, 2, 1)
        layout.addLayout(z_controls, 2, 2)
        layout.addWidget(self.z_limit_status, 3, 2, 1, 2)
        #layout.setColumnStretch(0, 0)  # "Z:"
        #layout.setColumnStretch(1, 0)  # value
        #layout.setColumnStretch(2, 1)  # remaining space goes here

        layout.addWidget(QLabel("Piezo:"), 4, 0)
        layout.addWidget(self.p_label, 4, 1)

        box.setLayout(layout)
        return box

    def update_positions(self):
        pos = self.controller.get_positions()
        if pos["x"] is not None:
            self.x_label.setText(f"{pos['x']*1e3:.2f} µm")
        if pos["y"] is not None:
            self.y_label.setText(f"{pos['y']*1e3:.2f} µm")
        if pos["z"] is not None:
            self.z_label.setText(f"{pos['z']*1e3:.2f} µm")
        if pos["piezo"] is not None:
            self.p_label.setText(f"{pos['piezo']} steps")

    def get_z_limit_from_input(self):
        text = self.z_limit_edit.text().strip()
        if not text:
            return None, None  # (value, error)
        try:
            z_limit = float(text) * 1e-3  # entry in µm → controller in mm
        except ValueError:
            return None, "Invalid number"
        if z_limit <= 0 or z_limit > 50:
            self.log.warning(f"User tried to set an invalid z-limit ({z_limit:.4f} mm)")
            return None, "Value must be between 50 and 50.000 µm"
        return z_limit, None

    def update_z_limit(self):
        z_limit, _ = self.get_z_limit_from_input()
        self.controller.pending_soft_limit = z_limit

    def toggle_z_limit(self):
        enabled = self.z_limit_btn.isChecked()
        if enabled:
            z_limit, error = self.get_z_limit_from_input()
            if error:
                self.z_limit_status.setText(error)
                self.z_limit_btn.setChecked(False)
                return
            if z_limit is None:
                pos = self.controller.get_positions_raw()
                if pos["z"] is None:
                    self.z_limit_status.setText("Z position unavailable")
                    self.z_limit_btn.setChecked(False)
                    return
                z_limit = pos["z"]
            self.controller.set_soft_limit(z_limit)
        else:
            self.controller.disable_soft_limit()

    # ------------------------------------------------
    # Step size
    # ------------------------------------------------
    def build_step_box(self):
        box = QGroupBox()
        layout = QHBoxLayout()
        self.step_group = QButtonGroup()
        steps = [0.1, 1, 5, 10]
        for s in steps:
            btn = QRadioButton(f"{s} µm")
            layout.addWidget(btn)
            self.step_group.addButton(btn)
            btn.toggled.connect(lambda checked, v=s: self.set_step(v) if checked else None)
            # set default step
            if s == 1:
                btn.setChecked(True)

        box.setLayout(layout)
        # controller gets the initial step size
        self.set_step(1)
        return box

    def set_step(self, value):
        step_mm = value * 1e-3
        self.xy_control.step = step_mm
        self.z_control.step = step_mm

    # ------------------------------------------------
    # Save / Load
    # ------------------------------------------------
    def build_save_box(self):
        box = QGroupBox()
        layout = QGridLayout()
        layout.setHorizontalSpacing(20)
        layout.setColumnStretch(0, 0)
        layout.setColumnStretch(1, 1)
        layout.setColumnStretch(2, 0)
        layout.setColumnStretch(3, 0)
        name_label = QLabel("Name")
        self.save_name_edit = QLineEdit()
        self.save_name_edit.setPlaceholderText("Enter position name")
        self.save_name_edit.returnPressed.connect(self.save_position)
        self.save_btn = QPushButton("Save position")
        self.save_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.save_btn.clicked.connect(self.save_position)
        layout.addWidget(name_label, 0, 0)
        layout.addWidget(self.save_name_edit, 0, 1, 1, 2)
        layout.addWidget(self.save_btn, 0, 3)
        pos_label = QLabel("Saved positions")
        self.position_combo = QComboBox()
        self.update_position_list()
        self.manage_btn = QPushButton("Manage positions")
        self.manage_btn.clicked.connect(self.open_position_manager)
        self.manage_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.goto_btn = QPushButton("Go to position")
        self.goto_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.goto_btn.clicked.connect(self.goto_position)
        layout.addWidget(pos_label, 1, 0)
        layout.addWidget(self.position_combo, 1, 1)
        layout.addWidget(self.manage_btn, 1, 2)
        layout.addWidget(self.goto_btn, 1, 3)
        box.setLayout(layout)
        return box
    
    def update_position_list(self):
        self.position_combo.clear()
        self.position_combo.addItems(PositionManager.list_positions())

    def open_position_manager(self):
        dlg = PositionManager(self)
        self.log.info(f"The position manager was opened. List of positions: {PositionManager.list_positions()}")
        dlg.exec()
        self.log.info(f"The position manager was closed. List of positions: {PositionManager.list_positions()}")
        # refresh combobox after dialog closes
        self.update_position_list()

    def save_position(self):
        name = self.save_name_edit.text().strip()
        if not name:
            QMessageBox.critical(self, "Error", "Please enter a position name first.")
            return
        name = re.sub(r'[^a-zA-Z0-9_\-]', '_', name)
        pos = self.controller.get_positions_raw()
        PositionManager.save_position(name, pos['x'], pos['y'], pos['z'])
        self.log.info(f"A new position was saved with name {name} and position x = {pos['x']}, y = {pos['y']}, z = {pos['z']}")
        self.status.showMessage(f"Position '{name}' saved", 3000)
        self.update_position_list()
        index = self.position_combo.findText(name)
        if index >= 0:
            self.position_combo.setCurrentIndex(index)

    def goto_position(self):
        name = self.position_combo.currentText()
        if not name:
            QMessageBox.warning(self, "Error", "No saved position selected.")
            return
        try:
            x, y, z = PositionManager.load_position(name)
            self.log.info(f"Succesfully loaded saved position with name {name}: x={x:.3f}, y={y:.3f}, z={z:.3f}")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Position file {name} could not be read.\nMake sure the file exists and contains valid data!")
            self.log.info(f"Position file {name} could not be read with error {e.with_traceback()}. Aborting")
            return
        # confirmation dialog before motion
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Warning)
        msg.setWindowTitle("Confirm stage movement")
        msg.setText("The stage will move to a saved position.")
        msg.setInformativeText(
            "Ensure there is no obstruction in the stage travel.\n\n"
            f"Target position:\n"
            f"x = {x:.3f}, y = {y:.3f}, z = {z:.3f}"
        )
        msg.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
        msg.setDefaultButton(QMessageBox.Cancel)
        msg.setWindowModality(Qt.ApplicationModal)

        ret = msg.exec_()

        if ret != QMessageBox.Ok:
            self.log.info("User aborted movement due to safety confirmation.")
            return
        # ------------------------------------------

        self.log.info("Stage is moving to the saved position")
        success = self.controller.move_to(x, y, z)

        if success:
            self.status.showMessage(f"Position '{name}' reached.", 3000)
            QMessageBox.information(self, "Success", "Moved to saved position.")
            self.log.info(f"Stage succesfully reached position {name}")
        else:
            QMessageBox.warning(self, "Warning", "Move did not fully converge to saved position.")
            self.log.warning("Move did not fully converge to saved position")

    # ------------------------------------------------
    # Velocity sliders
    # ------------------------------------------------
    def build_velocity_box(self):
        box = QGroupBox()

        layout = QGridLayout()

        self.xy_slider = QSlider(Qt.Horizontal)
        self.xy_slider.setRange(1,100)
        xy_val = QLabel("")

        self.z_slider = QSlider(Qt.Horizontal)
        self.z_slider.setRange(1,100)
        z_val = QLabel("")

        self.p_slider = QSlider(Qt.Horizontal)
        self.p_slider.setRange(1,100)
        p_val = QLabel("")

        # xy slider
        init_xy = self.controller.ref_max_xy * 1.0  # slider 50% = factor 1.0
        xy_val.setText(f"{init_xy:.1f} mm/s")
        self.xy_slider.setValue(50)
        self.xy_slider.valueChanged.connect(
            lambda v: xy_val.setText(f"{self.controller.set_max_velocity_xy(v):.1f} mm/s")
        )
        self.xy_slider.sliderReleased.connect(
            lambda: self.log.info(f"XY velocity set to {self.controller.max_xy:.1f} mm/s")
        )

        init_z = self.controller.ref_max_z * 1.0
        z_val.setText(f"{init_z:.1f} mm/s")
        self.z_slider.setValue(50)
        self.z_slider.valueChanged.connect(
            lambda v: z_val.setText(f"{self.controller.set_max_velocity_z(v):.1f} mm/s")
        )
        self.z_slider.sliderReleased.connect(
            lambda: self.log.info(f"Z velocity set to {self.controller.max_z:.1f} mm/s")
        )

        init_p = self.controller.ref_max_piezo * 1.0
        p_val.setText(f"{init_p:.0f} steps/s")
        self.p_slider.setValue(50)
        self.p_slider.valueChanged.connect(
            lambda v: p_val.setText(f"{self.controller.set_max_velocity_piezo(v):.0f} steps/s")
        )
        self.p_slider.sliderReleased.connect(
            lambda: self.log.info(f"Piezo velocity set to {self.controller.max_piezo:.1f} steps/s")
        )

        layout.addWidget(QLabel("XY"),0,0)
        layout.addWidget(self.xy_slider,0,1)
        layout.addWidget(xy_val,0,2)

        layout.addWidget(QLabel("Z"),1,0)
        layout.addWidget(self.z_slider,1,1)
        layout.addWidget(z_val,1,2)

        layout.addWidget(QLabel("Piezo"),2,0)
        layout.addWidget(self.p_slider,2,1)
        layout.addWidget(p_val,2,2)

        box.setLayout(layout)
        return box
    
    # ------------------------------------------------
    # Help + Remote Server Control
    # ------------------------------------------------
    def build_help_box(self):
        box = QGroupBox()
        layout = QHBoxLayout()
        # center buttons
        layout.addStretch()

        # Remote control button
        self.remote_btn = QPushButton("Enable Remote Control")
        self.remote_btn.setCheckable(True)
        self.remote_btn.setFixedWidth(160)
        self.remote_btn.setMinimumHeight(50)
        self.remote_btn.setSizePolicy(
            QSizePolicy.Fixed,
            QSizePolicy.Fixed
        )
        self.remote_btn.clicked.connect(
            self.toggle_remote_mode
        )
        layout.addWidget(self.remote_btn)
        # spacing between buttons
        layout.addSpacing(20)

        # Help button
        self.help_btn = QPushButton("Help")
        self.help_btn.clicked.connect(
            self.show_manual
        )
        self.help_btn.setFixedWidth(160)
        self.help_btn.setMinimumHeight(50)
        self.help_btn.setSizePolicy(
            QSizePolicy.Fixed,
            QSizePolicy.Fixed
        )
        layout.addWidget(self.help_btn)
        # center buttons
        layout.addStretch()
        box.setLayout(layout)

        return box
    
    def toggle_remote_mode(self):
        enabled = self.remote_btn.isChecked()
        #self.set_manual_controls_enabled(enabled)
        if enabled:
            self.controller.enable_remote_mode()
        else:
            self.controller.disable_remote_mode()

    def install_remote_mode_filters(self):
        widgets = [
            # sliders
            self.xy_slider,
            self.z_slider,
            self.p_slider,

            # z-limit
            self.z_limit_edit,
            self.z_limit_btn,

            # save/load
            self.goto_btn,
            self.save_btn,
            self.manage_btn,
            self.save_name_edit,
            self.position_combo,

            # z widget buttons
            self.z_control.up_btn,
            self.z_control.down_btn,
            self.z_control.stop_btn,
            self.z_control.labjack,
            self.z_control.piezo,

            # xy widget buttons
            self.xy_control.left_btn,
            self.xy_control.right_btn,
            self.xy_control.up_btn,
            self.xy_control.down_btn,
            self.xy_control.stop_btn,

            self.step_box,
        ]

        for w in widgets:
            w.installEventFilter(self)

    def trigger_remote_button_blink(self):
        # avoid overlapping blink animations
        if self.remote_blink_timer.isActive():
            return
        self.log.warning("User tried to push a button during remote control")
        self.remote_blink_state = False
        self.remote_blink_counter = 0
        self.remote_blink_timer.start(150)

    def remote_blink_step(self):
        self.remote_blink_state = (not self.remote_blink_state)
        # bright flash
        if self.remote_blink_state:
            self.remote_btn.setStyleSheet("""
                QPushButton {
                    background-color: rgb(255, 0, 0);
                    color: white;
                    font-weight: bold;
                }
            """)

        # normal remote-mode appearance
        else:
            self.remote_btn.setStyleSheet("""
                QPushButton {
                    background-color: rgb(140, 0, 0);
                    color: white;
                    font-weight: bold;
                }
            """)

        self.remote_blink_counter += 1
        # stop after 6 toggles
        if self.remote_blink_counter >= 6:
            self.remote_blink_timer.stop()
            # restore final appearance
            self.remote_btn.setStyleSheet("""
                QPushButton {
                    background-color: rgb(140, 0, 0);
                    color: white;
                    font-weight: bold;
                }
            """)

    def eventFilter(self, obj, event):
        if self.controller.remote_mode:
            blocked_events = [
                event.MouseButtonPress,
                event.MouseButtonDblClick,
                event.Wheel,
                event.KeyPress,
            ]

            if event.type() in blocked_events:
                self.trigger_remote_button_blink()
                return True

        return super().eventFilter(obj, event)
    
    def handle_controller_event(self, event: dict):
        etype = event.get("type")

        if etype == "soft_limit_hit":
            self.show_limit_warning(event)

        if etype == "axis_button_press":
            stage_map = ["X", "Y", "Z", "Piezo"]
            stage = stage_map[event["stage"]]
            state = "enabled" if event["enabled"] else "disabled"
            msg = f"Axis {stage} {state}"
            self.log.info(msg)
            self.status.showMessage(msg, 2000)

        elif etype == "axis_motion":
            stage_map = ["X", "Y", "Z", "Piezo"]
            axis = stage_map[event["axis"]]
            if event["moving"]:
                direction = "positive" if event["velocity"] > 0 else "negative"
                msg = f"{axis} motion started ({direction})"
            else:
                msg = f"{axis} motion stopped"
            self.log.info(msg)
            self.status.showMessage(msg, 500)

        elif etype == "zero_toggle":
            if event["enabled"]:
                msg = f"New zero position at {self.format_position(event['position'])}"
            else:
                msg = "Zero position disabled"
            self.log.info(msg)
            self.status.showMessage(msg, 1000)

        elif etype == "soft_limit_toggle":
            state = "enabled" if event["enabled"] else "disabled"
            enabled = event["enabled"]
            value = event["value"]
            self.z_limit_btn.setChecked(enabled)
            self.z_limit_btn.setText("Deactivate Z-limit" if enabled else "Activate Z-limit")
            if enabled and value is not None:
                self.z_limit_status.setText(f"Limit: {value*1e3:.1f} µm")
                msg = f"Soft limit {state} at z={value*1e3:.1f} µm"
            else:
                self.z_limit_status.setText("Z-limit disabled") 
                msg = f"Soft limit {state}"
            self.log.info(f"{msg[:-2]}um")
            self.status.showMessage(msg, 2000)
        
        elif etype == "remote_mode":
            enabled = event["enabled"]
            # when remote mode is enabled:
            # disable manual controls
            print(f"being called with {enabled}")
            #self.set_manual_controls_enabled(not enabled)
            self.remote_btn.blockSignals(True)
            self.remote_btn.setChecked(enabled)
            if enabled:
                self.remote_btn.setText("Disable Remote Control")
                self.remote_btn.setStyleSheet("""
                        QPushButton {
                            background-color: rgb(140, 0, 0);
                            color: white;
                            font-weight: bold;
                        }the 
                    """)
                self.log.info("Remote control mode enabled")
                self.status.showMessage("REMOTE CONTROL ACTIVE", 0)
            else:
                self.remote_btn.setText("Enable Remote Control")
                self.remote_btn.setStyleSheet("")
                self.log.info("Remote control mode disabled")
                self.status.showMessage("Manual control restored", 3000)
            self.remote_btn.blockSignals(False)

        else:
            self.log.info(f"Unhandled controller event: {event}")

    def show_limit_warning(self, event):
        pos = event.get("position")
        limit = event.get("limit")
        self.log.warning(f"Soft limit reached: z={pos:.4f} mm (limit={limit:.4f} mm)")
        QMessageBox.warning(self, "Z limit!",
            f"Z limit reached!\n\nPosition: {pos:.4f} mm\n"
            f"Limit: {limit:.4f} mm\n\n"
            f"For movements close to the Z-limit it is recommended to either use a small "
            "joystick velocity or move in small steps using the GUI buttons.\n" 
            "The Z-limit can be deactivated by pressing 'B' on the controller.\n\n"
            f"Press OK to continue"
        )
        # resume controller loop
        self.controller.running = True

    def format_position(self, pos):
        def fmt(v, d=3):
            return f"{v:.{d}f}" if v is not None else "—"

        return (
            f"X={fmt(pos['x'])}, "
            f"Y={fmt(pos['y'])}, "
            f"Z={fmt(pos['z'])}, "
            f"P={fmt(pos['piezo'], 1)}"
        )
    
    def check_zstage_homed(self):
        # check if Labjack was being homed already and open message box
        if self.controller.zstage.connected and not self.controller.zstage.homed:
            self.log.warning("Thorlabs Z-stage is not homed yet")
            # Create modal dialog
            msg = QMessageBox(self)
            msg.setWindowFlags(msg.windowFlags() | Qt.WindowStaysOnTopHint)
            msg.setIcon(QMessageBox.Warning)
            msg.setWindowTitle("Z-Stage Homing Required!")
            msg.setText("The Z-stage has not been homed.\nPress OK to start homing.")
            msg.setStandardButtons(QMessageBox.Ok)
            msg.setDefaultButton(QMessageBox.Ok)
            msg.setWindowModality(Qt.ApplicationModal)  # block rest of the GUI
            msg.raise_()
            msg.activateWindow()
            ret = msg.exec_()  # block until user clicks OK

            if ret == QMessageBox.Ok:
                self.log.info("Started homing procedure")
                # start homing (blocking call)
                self.controller.zstage.home_axis()
                self.controller.zstage.homed = True
                self.log.info("Succesfully homed the Thorlabs Z-stage")

    
    def check_hardware_connections(self):
        hardware = {"Joystick": self.controller.joystick.connected,
                "XY Stage": self.controller.standa.connected,
                "Z Stage": self.controller.zstage.connected,
                "Piezo Stage": self.controller.piezo.connected}
        
        # Create dialog if any hardware connection failed
        failed = [name for name, status in hardware.items() if not status]
        if failed:
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Warning)
            msg.setWindowTitle("Hardware connection failed!")
            msg.setText("The following hardware could not be initialized:")
            msg.setInformativeText("\n".join(f"• {name}" for name in failed))
            msg.setDetailedText(
                "Please check power, cables, and other software running.\n"
                "If the issue persists, restart the application or reconnect the devices.\n\n"
                "Press OK to continue the software without the hardware listed above. "
                "Press Quit and restart the software to let hardware changes take effect."
            )
            # buttons: OK + QUIT
            ok_btn = msg.addButton(QMessageBox.Ok)
            quit_btn = msg.addButton("Quit", QMessageBox.RejectRole)
            msg.setDefaultButton(ok_btn)
            msg.setWindowModality(Qt.ApplicationModal)
            msg.exec_()
            if msg.clickedButton() == quit_btn:
                sys.exit(0)

        for name, status in hardware.items():
            if status:
                self.log.info(f"{name} connected successfully")
            else:
                self.log.error(f"{name} not connected")

    # helper for pyinstaller executable loading files
    def resource_path(self, relative_path):
        if hasattr(sys, '_MEIPASS'):
            base_path = sys._MEIPASS
        else:
            base_path = os.path.abspath(".")
        return os.path.join(base_path, relative_path)

    def build_section_header(self, title):
        container = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 6)
        layout.setSpacing(3)
        label = QLabel(title)
        label.setStyleSheet("""
            QLabel {
                font-weight: bold;
                font-size: 10pt;
            }
        """)
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        #line.setFrameShadow(QFrame.Plain)
        line.setFrameShape(QFrame.NoFrame)
        line.setFixedHeight(1) 
        line.setStyleSheet("""
            QFrame {
                background-color:  #7a0000;
            }
        """)
        layout.addWidget(label)
        layout.addWidget(line)
        container.setLayout(layout)
        return container
    
    # help window
    def show_manual(self):
        self.log.info("User opened the manual")
        dialog = QDialog(self)
        dialog.setWindowTitle("Joystick & Stage Manual")
        layout = QVBoxLayout()
        # Joystick image
        pixmap = QPixmap(self.resource_path("joystick_annotated.png"))
        if not pixmap.isNull():
            label_img = QLabel()
            # scale the image to a max width
            max_width = 400
            label_img.setPixmap(pixmap.scaledToWidth(max_width, Qt.SmoothTransformation))
            label_img.setAlignment(Qt.AlignCenter)
            layout.addWidget(label_img)
        # Manual text
        manual_text = (
            "<b>Joystick Controls:</b><br>"
            "- <b>Knobs 0–3:</b><br>"
            "&nbsp;&nbsp;&nbsp;• Knob 0 → X stage<br>"
            "&nbsp;&nbsp;&nbsp;• Knob 1 → Y stage<br>"
            "&nbsp;&nbsp;&nbsp;• Knob 2 → Z stage<br>"
            "&nbsp;&nbsp;&nbsp;• Knob 3 → Piezo stage<br><br>"
            "- <b>Buttons:</b><br>"
            "&nbsp;&nbsp;&nbsp;• Axis buttons → Toggle knob activation<br>"
            "&nbsp;&nbsp;&nbsp;• A button → Toggle zero position<br>"
            "&nbsp;&nbsp;&nbsp;• B button → Set move limit for Z at chosen position<br>"
            "LED indicates active mode of each button.<br><br>"
            "<b>Software controls:</b><br>"
            "- <b>Manual movement:</b> Press buttons for single steps, hold for continuous motion.<br>"
            "- <b>Z-limit:</b> Enter maximum allowed travel in z-direction [µm] and press 'Activate'. "
            "If nothing is entered, it will take the current position as the z-limit.<br>"
            "- <b>Position management:</b> Save/load positions and move stages to a saved position.<br><br>"
            "<b>Safety:</b><br>"
            "Always ensure the stage path is clear to avoid collisions.<br><br>"
            "<b>Troubleshooting Hardware Connection:</b><br>"
            "1. Check all cables and connections.<br>"
            "2. Close other software that may block the stage.<br>"
            "3. Power cycle the stage.<br>"
            "4. Restart the PC if needed."
        )
        label_text = QLabel()
        label_text.setText(manual_text)
        label_text.setWordWrap(True)
        label_text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(label_text)
        dialog.setLayout(layout)
        dialog.resize(450, 400)
        dialog.show()