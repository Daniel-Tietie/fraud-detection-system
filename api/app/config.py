# settings for the fraud rules, each value can be changed with an environment variable
import os


class Settings:
    def __init__(
        self,
        max_amount=5000.0,
        max_travel_speed_kmh=900.0,
        travel_buffer_min=30.0,
        failed_login_window_min=10.0,
        failed_login_threshold=3,
        storage_backend="memory",
        queue_backend="memory",
    ):
        # Rule 1: used a predefined maximum amount for max amount for a transaction
        self.max_amount = max_amount
        # Rule 2: the impossible travel
        self.max_travel_speed_kmh = max_travel_speed_kmh  # I used the max speed an airplane travels at
        self.travel_buffer_min = travel_buffer_min  # extra time allowed for airports, delays and margin of error
        # rule 3: failed logins
        self.failed_login_window_min = failed_login_window_min
        self.failed_login_threshold = failed_login_threshold
        # Backends
        self.storage_backend = storage_backend  # memory (local) or dynamodb (AWS)
        self.queue_backend = queue_backend  # "memory" (local) or "sqs" (AWS)


def get_settings():
    return Settings(
        max_amount=float(os.getenv("MAX_AMOUNT", 5000)),
        max_travel_speed_kmh=float(os.getenv("MAX_TRAVEL_SPEED_KMH", 900)),
        travel_buffer_min=float(os.getenv("TRAVEL_BUFFER_MIN", 30)),
        failed_login_window_min=float(os.getenv("FAILED_LOGIN_WINDOW_MIN", 10)),
        failed_login_threshold=int(os.getenv("FAILED_LOGIN_THRESHOLD", 3)),
        storage_backend=os.getenv("STORAGE_BACKEND", "memory"),
        queue_backend=os.getenv("QUEUE_BACKEND", "memory"),
    )
