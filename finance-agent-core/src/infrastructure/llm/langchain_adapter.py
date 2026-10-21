"""LangChain compatibility adapter over the project LLM provider port."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator, Iterator, Sequence
from typing import cast

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.outputs import (
    ChatGeneration,
    ChatGenerationChunk,
    ChatResult,
)
from langchain_core.runnables import Runnable
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import ConfigDict, Field

from src.shared.llm.contracts import (
    ChatMessage,
    ChatRole,
    CompletionRequest,
    CompletionResult,
    LLMProviderPort,
    ModelRoute,
    StreamEvent,
)


class LangChainGatewayModelAdapter(BaseChatModel):
    """Expose the narrow LangChain model surface used by existing agents."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    provider: object
    route: ModelRoute
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    timeout_seconds: float = Field(default=60.0, gt=0.0)

    @property
    def _llm_type(self) -> str:
        return "project-llm-provider"

    def bind_tools(
        self,
        tools: Sequence[dict[str, object] | type | object],
        *,
        tool_choice: str | None = None,
        **kwargs: object,
    ) -> Runnable[object, AIMessage]:
        normalized = tuple(
            cast(dict[str, object], convert_to_openai_tool(tool)) for tool in tools
        )
        resolved_choice = "required" if tool_choice == "any" else tool_choice
        return self.bind(
            tools=normalized,
            tool_choice=resolved_choice,
            **kwargs,
        )

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: object | None = None,
        **kwargs: object,
    ) -> ChatResult:
        del stop, run_manager
        request = self._request(messages, kwargs)
        provider = cast(LLMProviderPort, self.provider)
        result = provider.complete(request)
        return ChatResult(
            generations=[ChatGeneration(message=_to_ai_message(result))],
            llm_output={"request_id": result.request_id, "model": result.model},
        )

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: object | None = None,
        **kwargs: object,
    ) -> ChatResult:
        del stop, run_manager
        request = self._request(messages, kwargs)
        provider = cast(LLMProviderPort, self.provider)
        result = await provider.acomplete(request)
        return ChatResult(
            generations=[ChatGeneration(message=_to_ai_message(result))],
            llm_output={"request_id": result.request_id, "model": result.model},
        )

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: object | None = None,
        **kwargs: object,
    ) -> Iterator[ChatGenerationChunk]:
        del stop, run_manager
        request = self._request(messages, kwargs)
        provider = cast(LLMProviderPort, self.provider)
        for event in provider.stream(request):
            chunk = _to_chat_generation_chunk(event)
            if chunk is not None:
                yield chunk

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: object | None = None,
        **kwargs: object,
    ) -> AsyncIterator[ChatGenerationChunk]:
        del stop, run_manager
        request = self._request(messages, kwargs)
        provider = cast(LLMProviderPort, self.provider)
        async for event in provider.astream(request):
            chunk = _to_chat_generation_chunk(event)
            if chunk is not None:
                yield chunk

    def _request(
        self, messages: list[BaseMessage], kwargs: dict[str, object]
    ) -> CompletionRequest:
        tools = _tool_definitions(kwargs.get("tools"))
        tool_choice = kwargs.get("tool_choice")
        resolved_choice = (
            cast(str | dict[str, object], tool_choice)
            if isinstance(tool_choice, str | dict)
            else None
        )
        return CompletionRequest(
            messages=tuple(_to_chat_message(message) for message in messages),
            route=self.route,
            request_id=f"lc-{uuid.uuid4().hex}",
            operation="langchain.chat_model",
            temperature=self.temperature,
            timeout_seconds=self.timeout_seconds,
            tools=tools,
            tool_choice=resolved_choice,
        )


def _to_chat_message(message: BaseMessage) -> ChatMessage:
    if isinstance(message, SystemMessage):
        role = ChatRole.SYSTEM
    elif isinstance(message, HumanMessage):
        role = ChatRole.USER
    elif isinstance(message, ToolMessage):
        role = ChatRole.TOOL
    else:
        role = ChatRole.ASSISTANT
    tool_calls = getattr(message, "tool_calls", ())
    return ChatMessage(
        role=role,
        content=_content_text(message.content),
        name=message.name,
        tool_call_id=(
            message.tool_call_id if isinstance(message, ToolMessage) else None
        ),
        tool_calls=tuple(
            cast(dict[str, object], call)
            for call in tool_calls
            if isinstance(call, dict)
        ),
    )


def _to_ai_message(result: CompletionResult) -> AIMessage:
    return AIMessage(
        content=result.text,
        tool_calls=[_to_langchain_tool_call(call) for call in result.tool_calls],
        response_metadata={"model": result.model, "request_id": result.request_id},
    )


def _to_chat_generation_chunk(event: StreamEvent) -> ChatGenerationChunk | None:
    if event.kind != "delta":
        return None
    return ChatGenerationChunk(
        message=AIMessageChunk(
            content=event.text,
            tool_call_chunks=[
                _to_langchain_tool_chunk(call) for call in event.tool_calls
            ],
        )
    )


def _to_langchain_tool_call(call: dict[str, object]) -> dict[str, object]:
    function = call.get("function")
    if isinstance(function, dict):
        name = str(function.get("name", ""))
        arguments = function.get("arguments", "{}")
        args = _json_object(arguments)
    else:
        name = str(call.get("name", ""))
        args = _json_object(call.get("args", {}))
    return {
        "id": str(call.get("id", f"call-{uuid.uuid4().hex}")),
        "name": name,
        "args": args,
    }


def _to_langchain_tool_chunk(call: dict[str, object]) -> dict[str, object]:
    converted = _to_langchain_tool_call(call)
    return {
        "id": converted["id"],
        "name": converted["name"],
        "args": json.dumps(converted["args"]),
        "index": 0,
    }


def _tool_definitions(value: object) -> tuple[dict[str, object], ...]:
    if not isinstance(value, list | tuple):
        return ()
    return tuple(
        cast(dict[str, object], item) for item in value if isinstance(item, dict)
    )


def _json_object(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return cast(dict[str, object], value)
    if isinstance(value, str):
        try:
            decoded: object = json.loads(value)
        except json.JSONDecodeError:
            return {}
        if isinstance(decoded, dict):
            return cast(dict[str, object], decoded)
    return {}


def _content_text(content: object) -> str:
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=True)
