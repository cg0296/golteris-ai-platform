"""
backend/llm/openai_provider.py — OpenAI GPT provider implementation.

Wraps the OpenAI Python SDK to implement the LLMProvider interface.
Supports function calling (tool-use) for structured extraction.

This module is never imported directly by agents — they use `call_llm()`
from `backend.llm.client`, which selects the provider based on config.

Requires: OPENAI_API_KEY environment variable.
"""

import json
import os

import openai

from backend.llm.provider import (
    LLMProvider,
    LLMProviderError,
    LLMRateLimitError,
    LLMResponse,
    LLMTimeoutError,
    ToolDefinition,
)


class OpenAIProvider(LLMProvider):
    """
    OpenAI GPT implementation of the LLM provider interface.

    Uses the OpenAI Python SDK for API calls. Converts our provider-agnostic
    ToolDefinition objects to OpenAI's function calling format, and converts
    OpenAI's response back to our unified LLMResponse.
    """

    def __init__(self):
        """
        Initialize the OpenAI client.

        Reads OPENAI_API_KEY from environment.
        """
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise LLMProviderError(
                "OPENAI_API_KEY not set. Add it to .env or set the environment variable."
            )
        self.client = openai.OpenAI(api_key=api_key)

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
        Make a single OpenAI API call.

        Converts ToolDefinition objects to OpenAI's function calling format,
        makes the call, and converts the response to LLMResponse.

        See LLMProvider.call() for full argument documentation.
        """
        try:
            # Build messages — OpenAI uses a messages array with role-based entries
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": user_prompt})

            # Build kwargs for the API call
            kwargs = {
                "model": model,
                "messages": messages,
                "max_completion_tokens": max_tokens,
                "temperature": temperature,
            }

            # Convert our ToolDefinition objects to OpenAI's function format.
            # OpenAI wraps each function in a {"type": "function", "function": {...}} object.
            if tools:
                kwargs["tools"] = [
                    {
                        "type": "function",
                        "function": {
                            "name": tool.name,
                            "description": tool.description,
                            "parameters": tool.input_schema,
                        },
                    }
                    for tool in tools
                ]

            # Make the API call
            response = self.client.chat.completions.create(**kwargs)

            # Extract content and tool calls from the response
            choice = response.choices[0]
            message = choice.message

            # Text content
            content = message.content

            # Tool calls — OpenAI returns these as a list on the message object
            tool_calls = []
            if message.tool_calls:
                for tc in message.tool_calls:
                    # OpenAI returns function arguments as a JSON string — parse it
                    tool_calls.append({
                        "name": tc.function.name,
                        "input": json.loads(tc.function.arguments),
                    })

            return LLMResponse(
                content=content,
                tool_calls=tool_calls,
                input_tokens=response.usage.prompt_tokens,
                output_tokens=response.usage.completion_tokens,
                model=response.model,
                raw_response=response,
            )

        except openai.APITimeoutError as e:
            raise LLMTimeoutError(f"OpenAI API timeout: {e}") from e
        except openai.RateLimitError as e:
            raise LLMRateLimitError(f"OpenAI rate limit: {e}") from e
        except openai.APIError as e:
            raise LLMProviderError(f"OpenAI API error: {e}") from e
