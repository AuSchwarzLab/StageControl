from hardware.base_stage_thorlabs import BaseStage


class MLJ250Stage(BaseStage):

    DEVICE_NAME = "APT Labjack"

    STEPS_PER_MM = 1228800

    MAX_POSITION_MM = 50

    MOVE_TO_SPEED = 50e6