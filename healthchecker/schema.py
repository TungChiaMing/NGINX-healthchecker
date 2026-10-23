from pydantic import BaseModel, Field
from typing import List, Tuple

class SleepRequest(BaseModel):
    """Receive the sleep time via JSON body for /sleep"""
    sleep_time: int = Field(
        ..., description="The time to sleep before responding.",
        example=5
    )

class StatusRequest(BaseModel):
    """Receive the status code via JSON body for /status"""
    status_code: int = Field(
        ..., description="The HTTP status code to echo in the POST response.",
        example=502
    )

class BehaviorRequest(BaseModel):
    """Customize query replied status code for /behavior"""
    rules: List[Tuple[int, int]] = Field(
        ...,
        description="List of (status_code, count) tuples. e.g., [(502, 3), (200, 4)]",
        example=[(502, 3), (200, 4)]
    )

class QueryRequest(BaseModel):
    """Receive the SQL query string in the /query route"""
    sql_query: str = Field(
        ..., description="The SQL query string provided by the user (no processing here)",
        example="SELECT SYSDATE FROM dual;"
    )

class ResponseRule(BaseModel):
    count: int = Field(
        ..., description="Number of times this status code should be repeated"
    )
    status_code: int = Field(
        ..., description="The HTTP Status Code to return"
    )
