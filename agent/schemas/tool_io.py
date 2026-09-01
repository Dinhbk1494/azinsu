from pydantic import BaseModel, Field
from typing import Literal


# ─── auth_login ───────────────────────────────────────────────────────────────

class AuthLoginInput(BaseModel):
    base_url: str
    login_endpoint: str = "/api/login"
    method: str = "POST"
    credentials: dict
    auth_type: Literal["form", "json", "basic", "oauth"] = "json"


class AuthLoginOutput(BaseModel):
    success: bool
    cookies: dict = {}
    headers: dict = {}
    user_info: dict | None = None
    error: str | None = None


# ─── endpoint_discover ────────────────────────────────────────────────────────

class Parameter(BaseModel):
    name: str
    location: Literal["path", "query", "body", "header", "cookie"]
    sample_value: str | None = None
    looks_like_id: bool = False


class Endpoint(BaseModel):
    url: str
    method: str
    parameters: list[Parameter] = []
    requires_auth: bool = True
    is_graphql: bool = False


class EndpointDiscoverInput(BaseModel):
    base_url: str
    auth: dict = {}
    methods: list[str] = ["GET", "POST", "PUT", "DELETE", "PATCH"]
    max_depth: int = 3
    include_graphql: bool = True


class EndpointDiscoverOutput(BaseModel):
    endpoints: list[Endpoint] = []
    parameters_with_id_indicators: list[Parameter] = []


# ─── id_mutate ────────────────────────────────────────────────────────────────

class Mutation(BaseModel):
    value: str
    strategy: str
    rationale: str


class IdMutateInput(BaseModel):
    original_value: str
    strategies: list[str] | None = None
    user_b_known_ids: list[str] | None = None


class IdMutateOutput(BaseModel):
    mutations: list[Mutation] = []


# ─── auth_compare ─────────────────────────────────────────────────────────────

class ContextResult(BaseModel):
    auth_label: str
    status_code: int
    response_length: int
    body_excerpt: str
    headers: dict = {}


class Difference(BaseModel):
    field: str
    value_a: str
    value_b: str


class AuthCompareInput(BaseModel):
    url: str
    method: str = "GET"
    path_params: dict = {}
    query_params: dict = {}
    body: dict | None = None
    request_headers: dict = {}
    auth_contexts: list[dict]


class AuthCompareOutput(BaseModel):
    results: list[ContextResult] = []
    differences: list[Difference] = []
    suggests_idor: bool = False
    confidence: float = 0.0


# ─── idor_confirm ─────────────────────────────────────────────────────────────

class IdorCandidate(BaseModel):
    url: str
    method: str
    vulnerable_param: str
    param_location: str
    original_value: str
    mutated_value: str
    param_in_query: dict = {}
    param_in_body: dict | None = None
    param_in_headers: dict = {}


class IdorConfirmInput(BaseModel):
    candidate: IdorCandidate
    user_a_auth: dict
    user_b_auth: dict
    user_b_known_data: dict = {}


class IdorConfirmOutput(BaseModel):
    confirmed: bool
    evidence: dict | None = None
    poc_request: dict | None = None
    poc_response: dict | None = None
    confidence: float = 0.0
    confirmation_method: str = ""
