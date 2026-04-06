"""
backend/llm/provider.py — Abstract base class for LLM providers.

Every LLM provider (Anthropic, OpenAI, etc.) must implement this interface.
The `call_llm()` function in `client.py` delegates to these implementations.

This abstraction exists so that:
- Agents never import provider SDKs directly
- Swapping providers is a config change, not a code change
- New providers are added by implementing one class

See REQUIREMENTS.md §2.5 for the architectural rationale.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LLMResponse:
    """
    Unified response from any LLM provider.

    Every provider implementation must return this exact shape, regardless of
    how the underlying SDK structures its response. This is what agents receive.

    Attributes:
        content: The text response from the LLM (or None if tool-use only)
        tool_calls: List of tool-use results (structured data from function calling).
                    Each item is a dict with 'name' and 'input' keys.
        input_tokens: Number of input tokens consumed (for cost calculation)
        output_tokens: Number of output tokens generated (for cost calculation)
        model: The actual model that was used (may differ from requested if aliased)
        raw_response: The full raw response object from the provider SDK,
                      preserved for debugging and the "View system reasoning" disclosure
    """
    content: str | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    raw_response: Any = None


@dataclass
class ToolDefinition:
    """
    A tool (function) that the LLM can call during generation.

    Used for structured extraction — agents define their expected output schema
    as a tool, and the LLM returns data matching that schema.

    This is the provider-agnostic representation. Each provider implementation
    converts this to its native format (Anthropic tool-use, OpenAI function calling).

    Attributes:
        name: Tool name (e.g., "extract_rfq")
        description: What the tool does (shown to the LLM)
        input_schema: JSON Schema defining the tool's parameters
    """
    name: str
    description: str
    input_schema: dict[str, Any]


class LLMProvider(ABC):
    """
    Abstract base class for LLM providers.

    Each provider (Anthropic, OpenAI, etc.) implements this class.
    The `call()` method is the only thing that varies per provider.

    Implementations must:
    - Convert ToolDefinition objects to the provider's native format
    - Make the API call using the provider's SDK
    - Convert the response to a unified LLMResponse
    - Raise standard exceptions for errors (see client.py for handling)
    """

    @abstractmethod
    def call(
        self,
        model: str,
        system_prompt: str | None,
        user_prompt: str,
        tools: list[ToolDefinition] | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> LLMResponse:
        """
        Make a single LLM API call.

        Args:
            model: Model identifier (e.g., "claude-sonnet-4-6", "gpt-4o")
            system_prompt: System-level instructions (optional)
            user_prompt: The user message / input to process
            tools: Optional list of tools the LLM can call (for structured extraction)
            max_tokens: Maximum output tokens (default 4096)
            temperature: Sampling temperature (default 0.0 for deterministic)

        Returns:
            LLMResponse with the unified response data

        Raises:
            LLMTimeoutError: Call timed out
            LLMRateLimitError: Provider rate limit hit
            LLMProviderError: Any other provider-side error
        """
        ...


class LLMTimeoutError(Exception):
    """The LLM API call timed out."""
    pass


class LLMRateLimitError(Exception):
    """The LLM provider's rate limit was hit."""
    pass


class LLMProviderError(Exception):
    """A provider-side error occurred (not timeout or rate limit)."""
    pass


class LLMCostCapExceeded(Exception):
    """
    The daily or monthly cost cap has been reached.
    C5 enforcement — no further LLM calls until the cap resets.
    """
    pass
