import logging
from collections import deque
from collections import defaultdict
from threading import Lock

class LogManager:
    def __init__(self, capacity=100):
        self.capacity = capacity
        self.system_buffer = deque(maxlen=capacity)
        self.user_buffers = defaultdict(lambda: deque(maxlen=capacity))
        self.lock = Lock()
        self.formatter = logging.Formatter('%(asctime)s - %(message)s', datefmt='%H:%M:%S')

    def add_log(self, user_id: int | None, message: str):
        with self.lock:
            if user_id:
                self.user_buffers[user_id].append(message)
            else:
                self.system_buffer.append(message)

    def get_user_logs(self, user_id: int):
        with self.lock:
            return list(self.user_buffers[user_id])

    def get_system_logs(self):
        with self.lock:
            return list(self.system_buffer)

# Global manager instance
log_manager = LogManager(capacity=100)

class LogBufferHandler(logging.Handler):
    def emit(self, record):
        if record.levelno < logging.INFO:
            return
        
        msg = self.format(record)
        # Extract user_id from record if exists
        user_id = getattr(record, "user_id", None)
        log_manager.add_log(user_id, msg)

logging.getLogger().addHandler(LogBufferHandler())
