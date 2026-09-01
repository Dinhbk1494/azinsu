from pydantic import BaseModel, Field
from typing import Literal
from datetime import datetime


class HttpRequest(BaseModel):
    method: str
    url: str
    headers: dict = {}
    cookies: dict = {}
    body: str | None = None


class HttpResponse(BaseModel):
    status_code: int
    headers: dict = {}
    body: str = ""
    elapsed_ms: float = 0.0


class Evidence(BaseModel):
    unauthorized_data: dict
    user_b_fields_found: list[str]
    raw_response_excerpt: str


class Finding(BaseModel):
    id: str
    target_url: str
    endpoint: str
    method: str
    vulnerable_param: str
    param_location: Literal["path", "query", "body", "header", "cookie"]
    idor_type: str
    description: str
    severity: Literal["low", "medium", "high", "critical"] = "high"
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: Evidence
    poc_request: HttpRequest
    poc_response: HttpResponse
    confirmed: bool = False
    timestamp: str = ""

    def model_post_init(self, __context):
        if not self.timestamp:
            self.timestamp = datetime.utcnow().isoformat()
