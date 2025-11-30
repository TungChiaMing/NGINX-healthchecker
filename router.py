from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse
from http import HTTPStatus
from typing import List, Callable, Any
from functools import wraps

from schema import BehaviorRequest, QueryRequest, StatusRequest, ResponseRule
from logger import Logger


class HealthCheckService:
    def __init__(self, logger: Logger, default_code: int = 200):
        if not isinstance(default_code, int):
            raise TypeError(f"default_code must be an int, got {type(default_code)}")

        self.logger = logger
        self.behavior_queue: List[ResponseRule] = []
        self.default_code: int = default_code

        self.router = APIRouter()
        self.setup_routes()

    @property
    def get_router(self) -> APIRouter:
        return self.router
    
    def setup_routes(self):
        # documentation redirects
        self.router.get("/docs/")(self.redirect_docs)
        self.router.get("/redoc/")(self.redirect_redoc)

        # status routes
        self.router.get("/status/{status_code}")(self.handle_exception(self.get_status))
        self.router.post("/status")(self.handle_exception(self.set_status))

        # behavior configuration route
        self.router.post("/behavior")(self.handle_exception(self.set_behavior))

        # main query listener route
        self.router.post("/query")(self.handle_exception(self.handle_query))

    async def redirect_docs(self):
        """Redirects /docs/ back to /docs"""
        return RedirectResponse(url="/docs")

    async def redirect_redoc(self):
        """Redirects /redoc/ back to /redoc"""
        return RedirectResponse(url="/redoc")

    async def get_status(self, status_code: int, request: Request, response: Response):
        """Set the response status code for this GET request using a path parameter"""
        if (error := self.validate_status_code(status_code, request, response)):
            return error

        http_status = HTTPStatus(status_code)
        phrase = http_status.phrase

        response.status_code = status_code
        content = {"request": f"{status_code} {phrase}", "return status code": f"{status_code} {phrase}"}
        request.state.response_body = content
        return content

    async def set_status(self, body: StatusRequest, request: Request, response: Response):
        """Set the immediate response status code for this POST request using a JSON body. Body Example: {"status_code": 502}"""

        status_code = body.status_code
        if (error := self.validate_status_code(status_code, request, response)):
            return error
        
        http_status = HTTPStatus(status_code)
        phrase = http_status.phrase
        
        response.status_code = status_code
        content = {"request": f"{status_code} {phrase}", "return status code": f"{status_code} {phrase}"}
        request.state.response_body = content
        return content


    async def set_behavior(self, body: BehaviorRequest, request: Request, response: Response):
        """Set the Nginx Upstream query response behavior. Body Example: {"rules": [(502, 3), (200, 4)]}"""
        queue = []
        for status_code, cnt in body.rules:
            if (error := self.validate_status_code(status_code, request, response)):
                return error
            queue.append(ResponseRule(count=cnt, status_code=status_code)) if cnt > 0 else None

        self.behavior_queue = queue

        content = {"message": f"set behavior {body.rules}"}

        request.state.response_body = content
        return content

    async def handle_query(self, query: QueryRequest, request: Request, response: Response):
        if not self.behavior_queue:
            status_code = self.default_code
            rule = "Default(Empty Queue)"
        else:
            current_rule = self.behavior_queue[0]
            status_code = current_rule.status_code

            current_rule.count -= 1
            rule = f"queue remaining: {current_rule.count}: {current_rule.status_code}"

            if current_rule.count <= 0:
                self.behavior_queue.pop(0)
                rule += " (finish setting behavior)"

        try:
            http_status = HTTPStatus(status_code)
            phrase = http_status.phrase
        except ValueError:
            phrase = "Unknown Status"

        response.status_code = status_code

        content = {
            "status_code": status_code,
            "message": phrase,
            "behavior": rule,
            "query": query.sql_query
        }

        request.state.response_body = content
        return content

    @staticmethod
    def handle_exception(fn: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return await fn(*args, **kwargs)
            except Exception as e:

                logger_instance = (
                    args[0].logger 
                    if args and hasattr(args[0], 'logger') 
                    else Logger("fallback_logger")
                )
                logger_instance.exception("Unhandled exception in API route: %s", e)
                return Response(content='{"error":"internal error"}', status_code=500)
        return wrapper
    
    def validate_status_code(self, status_code: int, request: Request, response: Response):
        try:
            HTTPStatus(status_code)
        except ValueError:
            response.status_code = HTTPStatus.BAD_REQUEST.value
            content = {
                "message": f"Invalid or unsupported HTTP status code {status_code}",
                "return status code": response.status_code
            }
            request.state.response_body = content
            return content
        return None