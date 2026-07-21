class EventBase:
    def __init__(self, timestamp: float, job_uid: str, event_type: str, payload: dict):
        self.timestamp = timestamp
        self.job_uid = job_uid
        self.event_type = event_type
        self.payload = payload