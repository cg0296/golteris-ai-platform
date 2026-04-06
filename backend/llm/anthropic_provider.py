"""
backend/llm/anthropic_provider.py — Anthropic Claude provider implementation.

Wraps the Anthropic Python SDK to implement the LLMProvider interface.
Supports tool-use (function calling) for structured extraction.

This module is never imported directly by agents — they use `call_llm()`
from `backend.llm.client`, which selects the provider based on config.

Requires: ANTHROPIC_API_KEY environment variable.
"""

import os

import anthropic

from backend.llm.provider import (
    LLMProvider,
    LLMProviderError,
    LLMRateLimitError,
    LLMResponse,
    LLMTimeoutError,
    ToolDefinition,
)


class AnthropicProvider(LLMProvider):
    """
    Anthropic Claude implementation of the LLM provider interface.

    Uses the Anthropic Python SDK for API calls. Converts our provider-agnostic
    ToolDefinition objects to Anthropic's tool-use format, and converts
    Anthropic's response back to our unified LLMResponse.
    """

    def __init__(self):
        """
        Initialize the Anthropic client.

        Reads ANTHROPIC_API_KEY from environment. The SDK handles this
        automatically, but we check explicitly to give a clear error message.
        """
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise LLMProviderError(
                "ANTHROPIC_API_KEY not set. Add it to .env or set the environment variable."
            )
        self.client = anthropic.Anthropic(api_key=api_key)

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
        Make a single Anthropic Claude API call.

        Converts ToolDefinition objects to Anthropic's native tool format,
        makes the call, and converts the response to LLMResponse.

        See LLMProvider.call() for full argument documentation.
        """
        try:
            # Build the messages list — Anthropic uses a messages array
            messages = [{"role": "user", "content": user_prompt}]

            # Build kwargs for the API call
            kwargs = {
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }

            # Add system prompt if provided (Anthropic takes it as a top-level param)
            if system_prompt:
                kwargs["system"] = system_prompt

            # Convert our ToolDefinition objects to Anthropic's tool format
            if tools:
                kwargs["tools"] = [
                    {
                        "name": tool.name,
                        "description": tool.description,
                        "input_schema": tool.input_schema,
                    }
                    for tool in tools
                ]

            # Make the API call
            response = self.client.messages.create(**kwargs)

            # Extract text content and tool-use results from the response.
            # Anthropic returns a list of content blocks — some are text, some are tool_use.
            text_parts = []
            tool_calls = []
            for block in response.content:
                if block.type == "text":
                    text_parts.append(block.text)
                elif block.type == "tool_use":
                    tool_calls.append({
                        "name": block.name,
                        "input": block.input,
                    })

            return LLMResponse(
                content="\n".join(text_parts) if text_parts else None,
                tool_calls=tool_calls,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                model=response.model,
                raw_response=response,
            )

        except anthropic.APITimeoutError as e:
            raise LLMTimeoutError(f"Anthropic API timeout: {e}") from e
        except anthropic.RateLimitError as e:
            raise LLMRateLimitError(f"Anthropic rate limit: {e}") from e
        except anthropic.APIError as e:
            raise LLMProviderError(f"Anthropic API error: {e}") from e
