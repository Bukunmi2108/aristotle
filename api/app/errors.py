class ServiceWakeTimeoutError(RuntimeError):
    def __init__(self, service: str):
        super().__init__(f"{service} service did not become ready in time")
        self.service = service
