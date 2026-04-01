import requests
from typing import Optional, List, Tuple
from project.logger import Logger
import time

import threading

class HealthCheckerApiClient:
    def __init__(self, base_url: str, logger: Optional[Logger] = None, timeout: int = 60):
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

    # def get_status(self, status_code: int) -> requests.Response:
    #     url = f"{self.base_url}/status/{status_code}"
    #     self.log_request("GET", url)
    #     response = requests.get(url, timeout=self.timeout)
    #     self.log_response("GET", url, response)
    #     return response

    def get_status(self, status_code: int, query: any) -> requests.Response:
        url = f"{self.base_url}/status/{status_code}"
        params = {}
        if query is not None:
            params["query"] = query

        self.log_request("GET", url, params=params)
        response = requests.get(url, params=params, timeout=self.timeout)
        self.log_response("GET", response.url, response)
        return response
    
    def get_status_count(self) -> Optional[int]:
        """
        Call the /status_count endpoint and return the number of times get_status has been accessed.
        """
        url = f"{self.base_url}/get_status_count"
        self.log_request("GET", url)
        response = requests.get(url, timeout=self.timeout)
        self.log_response("GET", url, response)

        if response.status_code == 200:
            try:
                data = response.json()
                return data.get("get_status_count")
            except ValueError:
                return None
        return None
    
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

    def benchmark_cache_get_status(
        self,
        status_code: int,
        query: str,
        iterations: int = 10000,
        output_file: Optional[str] = "cache_output.txt",
    ):
        latencies = []

        for i in range(iterations):
            start_ts = time.perf_counter()
            response = self.get_status(status_code, query=query)
            end_ts = time.perf_counter()

            latency = end_ts - start_ts
            latencies.append(latency)

            print(f"Req #{i:5d} | status={response.status_code} | time={latency * 1000:.3f} ms")

        total = sum(latencies)
        count = len(latencies)
        avg = total / count if count > 0 else 0
        minimum = min(latencies) if latencies else 0
        maximum = max(latencies) if latencies else 0

        # prepare summary
        summary_lines = [
            "====== Summary ======",
            f"Requests: {count}",
            f"Total time: {total:.3f} s",
            f"Avg latency: {avg * 1000:.3f} ms",
            f"Min latency: {minimum * 1000:.3f} ms",
            f"Max latency: {maximum * 1000:.3f} ms",
        ]

        # print summary
        for line in summary_lines:
            print(line)

        # write summary to file
        if output_file:
            with open(output_file, "w") as f:
                for line in summary_lines:
                    f.write(line + "\n")

        return {
            "total_time_s": total,
            "avg_latency_s": avg,
            "min_latency_s": minimum,
            "max_latency_s": maximum,
            "count": count,
            "latencies": latencies,
        }
    

def test_max_conn(client, query: str, num_requests: int = 5):
    def call_status(i):
        try:
            client.get_status(200, query=query)
            print(f"[Thread {i}] Request finished")
        except Exception as e:
            print(f"[Thread {i}] Exception: {e}")

    threads = []
    for i in range(num_requests):
        t = threading.Thread(target=call_status, args=(i,))
        t.start()
        threads.append(t)

    for t in threads:
        t.join()

# Example usage
if __name__ == "__main__":
    # client = HealthCheckerApiClient("http://localhost:8080")
    client = HealthCheckerApiClient("http://localhost:8080")

    # test_max_conn(client, query="", num_requests=2)

    for i in range(1000):
        time.sleep(10)
        client.get_status(200, query="SELECT * FROM users WHERE id = 1")

    # client.benchmark_cache_get_status(
    #     status_code=200,
    #     query="SELECT * FROM users WHERE id = 1",
    #     iterations=10000,
    #     output_file="no_cache_benchmark_output.txt"
    # )


    # response = client.get_status_count()
    # print(f"get_status_count: {response}")

    # client = HealthCheckerApiClient("http://localhost:8081/ABO")

    # # GET /status/502
    # response = client.post_status(502)
    # response = client.post_status(502)


    # client = HealthCheckerApiClient("http://localhost:8080/CWCP")

    # # GET /status/502
    # response = client.post_status(200)

