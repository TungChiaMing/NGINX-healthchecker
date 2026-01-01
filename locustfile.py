from locust import HttpUser, task, between
import json


from client import LocustHealthCheckerApiClient

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