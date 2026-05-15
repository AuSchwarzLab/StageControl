import ctypes
myappid = 'MyLab.MicroscopyStage.Control.v1'
ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)

import sys
import os
from PyQt5.QtWidgets import QApplication
from PyQt5 import QtGui, QtCore
from widgets.main_window import MainWindow

from hardware.mcmk4 import MCMK4
from hardware.piezo_motor import PiezoStage
from utils.multi_stage_controller import MultiStageController
from hardware.standa_xy_stage import Standa_XY
from hardware.thorlabs_zfs25b import ZFS25BStage


def resource_path(rel_path):
    base = getattr(sys, "_MEIPASS", os.path.dirname(__file__))
    return os.path.join(base, rel_path)

def set_dark_mode(app):
    app.setStyle("Fusion")
    dark_palette = QtGui.QPalette()
    dark_palette.setColor(QtGui.QPalette.Window, QtGui.QColor(53, 53, 53))
    dark_palette.setColor(QtGui.QPalette.WindowText, QtCore.Qt.white)
    dark_palette.setColor(QtGui.QPalette.Base, QtGui.QColor(35, 35, 35))
    dark_palette.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor(53, 53, 53))
    dark_palette.setColor(QtGui.QPalette.ToolTipBase, QtCore.Qt.white)
    dark_palette.setColor(QtGui.QPalette.ToolTipText, QtCore.Qt.white)
    dark_palette.setColor(QtGui.QPalette.Text, QtCore.Qt.white)
    dark_palette.setColor(QtGui.QPalette.Button, QtGui.QColor(53, 53, 53))
    dark_palette.setColor(QtGui.QPalette.ButtonText, QtCore.Qt.white)
    dark_palette.setColor(QtGui.QPalette.BrightText, QtCore.Qt.red)
    dark_palette.setColor(QtGui.QPalette.Highlight, QtGui.QColor(156, 16, 16))
    dark_palette.setColor(QtGui.QPalette.HighlightedText, QtCore.Qt.black)
    app.setPalette(dark_palette)
    font = app.font()
    font.setPointSize(10)
    app.setFont(font)

joystick = MCMK4()
xy = Standa_XY()
z = ZFS25BStage()
piezo = PiezoStage()
controller = MultiStageController(joystick, xy, z, piezo)


icon_path = resource_path("icon.ico")
os.makedirs("./positions", exist_ok=True)
app = QApplication(sys.argv)
icon = QtGui.QIcon(icon_path)
app.setWindowIcon(icon)
set_dark_mode(app)

window = MainWindow(controller)
window.show()
window.setWindowIcon(icon)

app.exec()
controller.stop()