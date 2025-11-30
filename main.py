import uvicorn
from fastapi import FastAPI, Request
from logging import LoggerAdapter

from router import HealthCheckService
from logger import Logger

import argparse
from util import check_port

def init_argparse():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=check_port, default=8080, help='listening port')
    parser.add_argument('--log_file', type=str, default='healthcheck_service.log', help='log file path')
    return parser

if __name__ == "__main__":

    parser = init_argparse()
    args = parser.parse_args()

    logger = Logger("healthcheck_service", log_file=args.log_file)

    app = FastAPI(title="HTTP listener for NGINX upstream healthchecks")

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        adapter = LoggerAdapter(logger, {"method": request.method, "route": request.url.path})
        request.state.logger_adapter = adapter
        response = await call_next(request)
        body = getattr(request.state, "response_body", None)
        if body is not None:
            adapter.info("Response body: %s | HTTP status: %s", body, response.status_code)
        else:
            adapter.info("Request finished, status=%s", response.status_code)
        return response

    healthcheck_service = HealthCheckService(logger)
    app.include_router(healthcheck_service.get_router)

    uvicorn.run(app, host="0.0.0.0", port=args.port)