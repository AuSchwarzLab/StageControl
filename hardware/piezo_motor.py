"""
@File    :   piezo_motor.py
@Time    :   2024/11/27 10:29:37
@Author  :   Paul Glaeser
@Version :   1.1
@Contact :   paul.glaeser@uni-tuebingen.de
@License :   <>
@Desc    :  Class for handling a Thorlabs PA13 piezo actuator
"""

from pylablib.devices import Thorlabs
import atexit
import warnings

class PiezoStage:
    """
    Class for controlling the Thorlabs PA13 piezo actuator.
    1 step ~ 20 nm
    
    """
    def __init__(self) -> None:
        self.connected = False
        self.stage = None
        self.piezo_running = False
        self.piezo_direction = None
        self.piezo_speed = 0

        warnings.filterwarnings("ignore")
        connected_devices = Thorlabs.list_kinesis_devices()
        if not len(connected_devices):
            print("Error: No Thorlabs devices connected!")
            return
        for e, device in enumerate(connected_devices):
            try:
                # look for the index of the device list containing the stage name
                _ = device.index("Piezo Motor Controller")
                serialnumber = connected_devices[e][0]
            except ValueError:
                pass
        try:
            self.stage = Thorlabs.KinesisPiezoMotor(serialnumber)
            if self.stage.get_enabled_channels == None:
                self.stage.enable_channels(1)
                self.stage.setup_drive(max_voltage=120, velocity=500, acceleration=1000)
            self.connected = True
            atexit.register(self.close)
            print("Piezo stage initialized.")
        except (Thorlabs.ThorlabsError, NameError):
            print("The Piezo stage was probably opened before or is not even connected!")
            return
                    

    def _move(self, direction: str = "+", steps: float = 1) -> None:
        self.stage.setup_drive(max_voltage=115, velocity=500, acceleration=1000)
        self.stage.move_by(int(direction + str(steps)))

    def move_relative(self, steps: int):
        current = self.stage.get_position()
        self.stage.move_to(current + steps)
        self.stage.wait_move()

    def set_velocity(self, velocity_steps_s):
        try:
            # deadband to avoid jitter
            if abs(velocity_steps_s) < 3:
                velocity_steps_s = 0

            # STOP condition
            if velocity_steps_s == 0:
                if self.piezo_running:
                    self.stage.stop()
                    self.piezo_running = False
                    self.piezo_direction = None
                return
            direction = "+" if velocity_steps_s > 0 else "-"
            speed = abs(velocity_steps_s)

            # Only update if something actually changed
            if (not self.piezo_running or
                direction != self.piezo_direction or
                abs(speed - self.piezo_speed) > 5):

                # Update jog parameters (this is the correct API!)
                self.stage.setup_jog(
                    velocity=int(speed),
                    acceleration=int(1000)  # tune this
                )

                # Only re-trigger jog if needed
                if not self.piezo_running or direction != self.piezo_direction:
                    self.stage.jog(direction, kind="continuous")

                self.piezo_running = True
                self.piezo_direction = direction
                self.piezo_speed = speed

        except Exception as e:
            print(f"Piezo exception: {e}")
            return

    def get_position(self) -> float:
        """
        Get the current position of the piezo motor in number of steps
        """
        return self.stage.get_position()
    
    def stop(self) -> None:
        self.stage.stop()

    def close(self):
        if self.connected:
            self.stage.close()
