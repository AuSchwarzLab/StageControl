from abc import ABC
from pylablib.devices import Thorlabs
import atexit
import warnings


class BaseStage(ABC):
    """
    Generic abstract base class for Thorlabs Z stages.
    """

    DEVICE_NAME = None
    STEPS_PER_MM = None
    MAX_POSITION_MM = None
    MOVE_TO_SPEED = None

    def __init__(self) -> None:
        self.connected = False
        self.homed = False

        warnings.simplefilter("ignore")

        serialnumber = self._find_device()
        if serialnumber is None:
            print(f"Error: Could not find device '{self.DEVICE_NAME}'")
            return
        try:
            self.stage = Thorlabs.KinesisMotor(serialnumber)
            self.homed = self.stage.is_homed()
            self.connected = True
            atexit.register(self.close)
            print("Initialization complete")

        except Thorlabs.ThorlabsError:
            print("The stage is already opened or not connected.")

    def _find_device(self):
        connected_devices = Thorlabs.list_kinesis_devices()
        if not connected_devices:
            print("Error: No Thorlabs devices connected!")
            return None
        for device in connected_devices:
            try:
                device.index(self.DEVICE_NAME)
                return device[0]
            except ValueError:
                pass
        return None

    @property
    def steps_per_mm(self):
        return self.STEPS_PER_MM

    def move(self, distance_mm: float) -> None:
        if self.stage.is_moving():
            return

        try:
            steps = distance_mm * self.steps_per_mm

            self.stage.setup_velocity(
                acceleration=50e4,
                max_velocity=50e6,
                scale=False
            )

            self.stage.move_by(distance=steps, scale=False)

        except Thorlabs.ThorlabsError:
            print("Movement failed (possibly motion limit reached).")

    def move_to(self, target_position_mm: float) -> None:
        if self.stage.is_moving():
            return

        if not (0 <= target_position_mm <= self.MAX_POSITION_MM):
            print("Target position outside valid range.")
            return

        self.stage.setup_velocity(
            acceleration=50e4,
            max_velocity=self.MOVE_TO_SPEED,
            scale=False
        )

        self.stage.move_to(
            target_position_mm * self.steps_per_mm,
            scale=False
        )

        self.stage.wait_move()

    def set_velocity(self, velocity_mm: float) -> None:
        velocity_steps = velocity_mm * self.steps_per_mm
        #print(f"velocity steps: {velocity_steps:.1f}")
        try:
            if abs(velocity_steps) < 100:
                self.stage.stop()
                return
            direction = "-" if velocity_steps > 0 else "+"
            self.stage.setup_velocity(
                acceleration=20e4,
                max_velocity=abs(velocity_steps),
                scale=True
            )
            self.stage.jog(direction)
        except Exception:
            print(Exception)
            pass

    def stop(self) -> None:
        try:
            self.stage.stop(immediate=True)
        except Exception:
            print("Stopping stage failed.")

    def get_position(self) -> float:
        return (
            self.stage.get_position(scale=False)
            / self.steps_per_mm
        )

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