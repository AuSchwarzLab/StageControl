from pathlib import Path
from datetime import datetime
import logging


class StageControlLogger:
    """
    Central application logger.
    Creates one logfile per session.
    """

    def __init__(self, log_dir="./logs"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        logfile = self.log_dir / f"session_{timestamp}.log"

        self.logger = logging.getLogger("StageControl")
        self.logger.setLevel(logging.INFO)

        # Prevent duplicate handlers if re-instantiated
        if not self.logger.handlers:

            file_handler = logging.FileHandler(logfile)
            file_handler.setLevel(logging.INFO)

            formatter = logging.Formatter(
                "%(asctime)s | %(levelname)s | %(message)s",
                "%Y-%m-%d %H:%M:%S"
            )

            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)

        self.info(f"Log started --> {logfile}")

    # -------------------------------------------------
    # Convenience wrappers
    # -------------------------------------------------
    def info(self, msg):
        self.logger.info(msg)

    def warning(self, msg):
        self.logger.warning(msg)

    def error(self, msg):
        self.logger.error(msg)