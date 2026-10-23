from locust import HttpUser, task, between
import json


class LocustHealthCheckerApiClient:
    """
    Locust-friendly client wrapper for HealthCheckerApiClient.
    support catch_response=True
    """
    def __init__(self, locust_client, timeout: int = 10):
        self.client = locust_client
        self.timeout = timeout

    def post_status(self, status_code: int, **kwargs):
        json_body = {"status_code": status_code}
        return self.client.post("/status", json=json_body, **kwargs)

    def get_status(self, status_code: int, **kwargs):
        url = f"/status/{status_code}"
        return self.client.get(url, **kwargs)
    


class ApiUser(HttpUser):
    wait_time = between(0.5, 1.5)

    def on_start(self):
        self.client_api = LocustHealthCheckerApiClient(self.client)

    @task(3)
    def get_status_task(self):
        with self.client_api.get_status(200, catch_response=True) as response:
            if response.status_code != 200:
                response.failure(f"Unexpected status code: {response.status_code}")
            else:
                response.success()

    @task(1)
    def post_status_task(self):
        with self.client_api.post_status(200, catch_response=True) as response:
            if response.status_code != 200:
                response.failure(f"Unexpected status code: {response.status_code}")
            else:
                response.success()