"""Error response contract shared by every API endpoint."""

from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    """One specific problem, for example a single invalid request field."""

    field: str | None = Field(
        default=None, description="Location of the problem, such as `body.title`."
    )
    message: str
    type: str


class ErrorBody(BaseModel):
    code: str = Field(description="Stable, machine-readable error code.")
    message: str = Field(description="Human-readable summary that is safe to display.")
    request_id: str = Field(description="Correlates this response with server logs.")
    details: list[ErrorDetail] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    """Envelope returned for every non-2xx response."""

    error: ErrorBody
