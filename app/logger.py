import logging
from collections import deque
from datetime import datetime

class LogBuffer(logging.Handler):
    def __init__(self, capacity=100):
        super().__init__()
        self.buffer = deque(maxlen=capacity)
        self.formatter = logging.Formatter('%(asctime)s - %(message)s', datefmt='%H:%M:%S')

    def emit(self, record):
        # Filter out noisy or technical logs
        if record.name.startswith("sqlalchemy") or record.name.startswith("apscheduler") or record.name.startswith("uvicorn"):
            return
        
        # Only log INFO and higher, skip debug/trace
        if record.levelno < logging.INFO:
            return

        msg = self.format(record)
        # Clean up timestamp if redundant
        self.buffer.append(msg)

    def get_logs(self):
        return list(self.buffer)

# Global buffer instance
log_buffer = LogBuffer(capacity=100)
logging.getLogger().addHandler(log_buffer)
