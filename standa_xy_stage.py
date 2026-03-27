"""
@File    :   standa_xy_stage.py
@Time    :   2024/11/27 10:30:01
@Author  :   Paul Glaeser
@Version :   1.1
@Contact :   paul.glaeser@uni-tuebingen.de
@License :   <>
@Desc    :  Class for handling a Standa XY stage
"""

import libximc.highlevel as ximc
from typing import Tuple
import atexit

class Standa_XY:
    """
    Class for Standa translational XY-stage
    """
    def __init__(self):
        self.connected = False
        self.axis_1 = None
        self.axis_2 = None
        atexit.register(self.close)
        try:
            devices = ximc.enumerate_devices(
                ximc.EnumerateFlags.ENUMERATE_NETWORK |
                ximc.EnumerateFlags.ENUMERATE_PROBE
            )

            if len(devices) < 2:
                print("Not enough Standa axes found.")
                return

            self.axis_1 = ximc.Axis(devices[1]['uri'])
            self.axis_1.open_device()
            self.axis_2 = ximc.Axis(devices[0]['uri'])
            self.axis_2.open_device()

            engine_settings = self.axis_1.get_engine_settings()
            self.conversion_coeff = 0.0025
            self.axis_1.set_calb(self.conversion_coeff, engine_settings.MicrostepMode)
            self.axis_2.set_calb(self.conversion_coeff, engine_settings.MicrostepMode)

            settings = self.axis_1.get_move_settings_calb()
            settings.Speed = 3.0
            settings.Decel = 3.0
            settings.Accel = 3.0
            self.axis_1.set_move_settings_calb(settings)
            self.axis_2.set_move_settings_calb(settings)

            self.connected = True
            print("Standa XY stage connected.")

        except Exception as e:
            print("Standa connection failed:", e)


    def move(self, axis: str= "x", distance_mm: float = 1) -> None:
        """
        Move the specified axis for a certain distance in the desired direction

        Parameters
        ---------
        str axis: select axis for x or y movement
        float distance_mm: distance in millimeters to travel

        Returns
        ---------
        None
        
        """
        if axis == "x":
            current_pos = self.axis_1.get_position_calb()
            self.axis_1.command_move_calb(current_pos.Position + distance_mm)
            #self.axis_1.command_wait_for_stop(refresh_interval_ms=5)
        if axis == "y":
            current_pos = self.axis_2.get_position_calb()
            self.axis_2.command_move_calb(current_pos.Position + distance_mm)
            #self.axis_1.command_wait_for_stop(refresh_interval_ms=5)

    def move_relative(self, axis: str, distance_mm: float):
        if axis == "x":
            current = self.axis_1.get_position_calb().Position
            self.axis_1.command_move_calb(current + distance_mm)
        elif axis == "y":
            current = self.axis_2.get_position_calb().Position
            self.axis_2.command_move_calb(current + distance_mm)

    def move_to(self, axis: str, target_position: float):
        if axis == "x":
            self.axis_1.command_move_calb(target_position)
        if axis == "y":
            self.axis_2.command_move_calb(target_position)

    def close(self) -> None:
        if self.connected:
            self.axis_1.close_device()
            self.axis_2.close_device()

    def get_position(self) -> Tuple[float, float]:
        x = self.axis_1.get_position_calb().Position
        y = self.axis_2.get_position_calb().Position
        return (x, y)
    
    def stop(self) -> None:
        self.axis_1.command_stop()
        self.axis_2.command_stop()

    def to_zero(self) -> None:
        self.axis_1.command_move_calb(0)
        self.axis_2.command_move_calb(0)
