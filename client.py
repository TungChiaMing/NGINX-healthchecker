import requests
from typing import Optional, List, Tuple
from project.logger import Logger

class HealthCheckerApiClient:
    def __init__(self, base_url: str, logger: Optional[Logger] = None, timeout: int = 10):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.logger = logger or Logger("HealthCheckerApiClient", log_file="ap.log")

    def log_request(self, method: str, url: str, **kwargs):
        self.logger.info(
            "Request: %s %s | Params: %s | JSON: %s",
            method, url, kwargs.get("params"), kwargs.get("json"),
            extra={"method": method, "route": url}
        )

    def log_response(self, method: str, url: str, response: requests.Response):
        try:
            body = response.json()
        except ValueError:
            body = response.text
        self.logger.info(
            "Response: %s %s | Status: %d | Body: %s",
            method, url, response.status_code, body,
            extra={"method": method, "route": url}
        )

    def get_status(self, status_code: int) -> requests.Response:
        url = f"{self.base_url}/status/{status_code}"
        self.log_request("GET", url)
        response = requests.get(url, timeout=self.timeout)
        self.log_response("GET", url, response)
        return response

    def post_status(self, status_code: int) -> requests.Response:
        url = f"{self.base_url}/status"
        json_body = {"status_code": status_code}
        self.log_request("POST", url, json=json_body)
        response = requests.post(url, json=json_body, timeout=self.timeout)
        self.log_response("POST", url, response)
        return response

    def set_behavior(self, rules: List[Tuple[int, int]]) -> requests.Response:
        url = f"{self.base_url}/behavior"
        json_body = {"rules": rules}
        self.log_request("POST", url, json=json_body)
        response = requests.post(url, json=json_body, timeout=self.timeout)
        self.log_response("POST", url, response)
        return response

    def query(self, sql_query: str) -> requests.Response:
        url = f"{self.base_url}/query"
        json_body = {"sql_query": sql_query}
        self.log_request("POST", url, json=json_body)
        response = requests.post(url, json=json_body, timeout=self.timeout)
        self.log_response("POST", url, response)
        return response

# Example usage
if __name__ == "__main__":
    client = HealthCheckerApiClient("http://localhost:8081/ABO")

    # GET /status/502
    response = client.post_status(502)
    response = client.post_status(502)


    client = HealthCheckerApiClient("http://localhost:8080/CWCP")

    # GET /status/502
    response = client.post_status(200)

