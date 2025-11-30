# Health Check Service

This project provides an HTTP-based health check service for NGINX upstream simulation.

It allows you to dynamically control response status codes and behaviors for testing NGINX behaviors.

The service is implemented using [FastAPI](chatgpt://generic-entity?number=0) and served with [Uvicorn](chatgpt://generic-entity?number=1). A standalone executable (`.exe`) is also provided.

---

## 1. Features

- Control HTTP status responses
- Queue-based response behavior control
- Request/Response logging
---

## 2. System Requirements

### For EXE Version
- Windows 10 / 11
- No Python installation is required

### For Source Code Version
- Python 3.9+
- pip
- Virtual environment recommended

---

## 3. Usage

Run the `exe` directly from the command line:

```bash
healthcheck_service.exe --port 8080 --log_file healthcheck.log
```

Run the `source code` directly:
```bash
pip install -r requirements.txt
python3 main.py
```

## 4. API Base URL

The service listens on the following base URL by default:

`http://localhost:8080`

You can view the interactive API documentation (Swagger UI) by navigating to:

`http://localhost:8080/docs`

This allows you to explore all available endpoints, send test requests, and view the request/response schemas directly from your browser.


If you start the service with a custom port like `9000`

Then the base URL becomes:

`http://localhost:9000`

All API endpoints described below are relative to this base URL.  
All request and response bodies use JSON format unless otherwise specified.

---

## 5. Status Control APIs

These APIs allow you to dynamically control the HTTP status code returned by the server.


### 5.1 Get Status by URL Path

Returns the specified HTTP status code.

Method: `GET`

Endpoint: `/status/{status_code}`


Example: `GET /status/502`


#### Example Success Response

```json
{
  "request": "502 Bad Gateway",
  "return status code": "502 Bad Gateway"
}
```

#### Example Error Response (Invalid Status Code)

```json
{
  "message": "Invalid or unsupported HTTP status code 999",
  "return status code": 400
}
```

---

### 5.2 Set Status by JSON Body

Sets the response status code using a JSON request body.

Method:   `POST`

Endpoint: `/status`

Example post raw json body:

```json
{
  "status_code": 503
}
```

#### Example Success Response

```json
{
  "request": "503 Service Unavailable",
  "return status code": "503 Service Unavailable"
}
```

#### Example Error Response (Invalid Status Code)

```json
{
  "message": "Invalid or unsupported HTTP status code 999",
  "return status code": 400
}
```

## 6. Behavior Queue API

This API configures a **sequential response behavior queue** for the `/query` endpoint.  
You can define multiple `(status_code, count)` rules, and the server will return them in FIFO order for consecutive `/query` requests.

Each rule means:
- Return `status_code`
- For `count` number of `/query` requests

Once all rules are consumed, `/query` falls back to the default status code (`200` by default).


### Endpoint

- Method: `POST`
- URL: `/behavior`

### Request Body (JSON)

| Field | Type | Description |
|------|------|-------------|
| `rules` | `List[List[int, int]]` | List of `[status_code, count]` pairs |

#### Example

```json
{
  "rules": [
    [502, 3],
    [200, 4]
  ]
}
```


## 7. Query Handling API

This API simulates an upstream query request.  
The returned HTTP status code is determined by the **Behavior Queue**.  
If the queue is empty, the server returns the **default status code (200)**.

This API is mainly used for:
- NGINX upstream health check simulation
- Load balancer failover testing


### Endpoint

- Method: `POST`
- URL: `/query`

### Request Body (JSON)

| Field | Type | Description |
|------|------|-------------|
| `sql_query` | `string` | Query text used only for logging and response display |

#### Example Request Body

```json
{
  "sql_query": "SELECT SYSDATE FROM dual;"
}
```

## 8. Logging Format
All API requests and responses are logged using the `Logger` class.
Logs include timestamp, HTTP method, route, log level, and message. 

By default, logs are written to a file (default `healthcheck_service.log`) and also printed to the console with colored output.

### Log Format

- `<LEVEL>` → Log severity (e.g., INFO, DEBUG, ERROR)  
- `<YYYY-MM-DD HH:MM:SS>` → Timestamp of the log  
- `<METHOD>` → HTTP method of the request (e.g., GET, POST)  
- `<ROUTE>` → API endpoint path  
- `<MESSAGE>` → Log message, which can include request or response details  


### Example Logs

```bash
INFO 2025-11-30 01:09:40 [POST /behavior] Response body: {'message': 'set behavior [(502, 3), (200, 4)]'} | HTTP status: 200
INFO 2025-11-30 01:10:03 [POST /query] Response body: {'status_code': 502, 'message': 'Bad Gateway', 'behavior': 'queue remaining: 2: 502', 'query': 'SELECT SYSDATE FROM dual;'} | HTTP status: 502
```

The first example shows a `/behavior` API call setting the response behavior queue.  
The second example shows a `/query` API call, including the actual SQL query, the returned HTTP status, and the remaining behavior queue state.  
