"""Shared browser/integration request contracts; no HTTP or storage imports."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Question = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4_000)]
DocumentName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]


class AgentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: Question
    document_filter: DocumentName | None = None


class HistoryTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["user", "assistant"]
    content: Annotated[str, StringConstraints(min_length=1, max_length=16_000)]


class ConversationRequest(AgentRequest):
    history: list[HistoryTurn] | None = Field(default=None, max_length=10)
