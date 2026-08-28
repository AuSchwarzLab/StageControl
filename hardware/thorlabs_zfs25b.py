from hardware.base_stage_thorlabs import BaseStage


class ZFS25BStage(BaseStage):

    DEVICE_NAME = "Kinesis Stepper Controller"

    STEPS_PER_MM = 2184533

    MAX_POSITION_MM = 24.9

    MOVE_TO_SPEED = 100e6