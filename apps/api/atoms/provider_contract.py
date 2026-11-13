"""Worker-facing generation results and errors."""
from dataclasses import dataclass


class ModelError(Exception):
    def __init__(self, code, message, usage=None, uncertain=False):
        self.code = code
        self.usage = usage
        self.uncertain = uncertain
        super().__init__(message)


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int
    request_id: str | None = None


@dataclass(frozen=True)
class ModelResult:
    content: str
    usage: Usage
