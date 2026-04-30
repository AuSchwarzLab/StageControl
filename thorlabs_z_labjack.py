"""
@File    :   thorlabs_z_stage.py
@Time    :   2024/11/27 10:30:01
@Author  :   Paul Glaeser
@Version :   1.1
@Contact :   paul.glaeser@uni-tuebingen.de
@License :   <>
@Desc    :  Class for handling a Thorlabs MLJ250
"""

from pylablib.devices import Thorlabs
import atexit
import warnings

class Z_Stage:
    """
    Class for controlling a Thorlabs Z-stage MLJ250 (Labjack)
    1228800 steps = 1 mm
    """
    def __init__(self) -> None:
        """
        Constructor for initializing Labjack Z-stage
        Check connection and check for homing
        """
        self.connected = False
        self.homed = False
        warnings.simplefilter("ignore")

        connected_devices = Thorlabs.list_kinesis_devices()
        if not len(connected_devices):
            print("Error: No Thorlabs devices connected!")
            return
        for e, device in enumerate(connected_devices):
            try:
                # look for the index of the device list containing the stage name
                _ = device.index("APT Labjack")
                serialnumber = connected_devices[e][0]
            except ValueError:
                pass
        try:
            self.stage = Thorlabs.KinesisMotor(serialnumber)
            self.homed = self.stage.is_homed()
            atexit.register(self.close)
            self.connected = True
            self.steps_per_mm = 1228800
        except (Thorlabs.ThorlabsError, NameError):
            print("The Z-stage was probably opened before or is not even connected!")
            return
        print("Initialization complete")


    def move(self, distance_mm: float) -> None:
        """
        Move stage for a distance in millimeters

        Parameters
        ---------
        float distance_mm: distance to travel

        Returns
        ---------
        None
        """
        if self.stage.is_moving():
            return
        try:
            steps = distance_mm * self.steps_per_mm
            self.stage.setup_velocity(acceleration=50e4, max_velocity=50e6, scale=False)
            self.stage.move_by(distance=steps, scale=False)
        except Thorlabs.ThorlabsError:
            print("You are probably at the limit of the moving range, aborting ...")
            return
        
    def move_to(self, target_position):
        if self.stage.is_moving():
            return
        if 0 < target_position < 61440000:
            self.stage.setup_velocity(acceleration=50e4, max_velocity=50e6, scale=False)
            self.stage.move_to(target_position * self.steps_per_mm, scale=False)
            self.stage.wait_move()
        
    def set_velocity(self, velocity_mm):
        velocity_steps = velocity_mm * self.steps_per_mm
        try:
            if abs(velocity_steps) < 100:
                self.stage.stop()
                return

            direction = "-" if velocity_steps > 0 else "+"

            self.stage.setup_velocity(
                acceleration=50e3,
                max_velocity=abs(velocity_steps),
                scale=False
            )

            self.stage.jog(direction)
        except Exception:
            return

    def stop(self) -> None:
        try:
            self.stage.stop(immediate=True)
        except Exception:
            print("Stopping the Z-stage did not succeed.")
            return

    def get_position(self) -> float:
        """
        Return the current absolute position of the stage in millimeters
        """
        return self.stage.get_position(scale=False) / self.steps_per_mm
    
    def home_axis(self) -> None:
        self.stage.home(force=True)
        self.stage.wait_for_home()
        
    def close(self):
        if self.connected:
            try:
                self.stage.stop(immediate=True)
            except Exception:
                pass
            self.stage.close()