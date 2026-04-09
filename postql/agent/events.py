from __future__ import annotations

import logging
from typing import Any

from agents import (
    ItemHelpers,
    MessageOutputItem,
    RawResponsesStreamEvent,
    ReasoningItem,
    RunItemStreamEvent,
    ToolCallItem,
    ToolCallOutputItem,
)

from ..logging import logger
from ..run_artifacts import RunArtifacts


def _summarize_raw_response_event(raw_event: Any) -> dict[str, Any]:
    return {
        "type": str(getattr(raw_event, "type", type(raw_event).__name__)),
        "data": str(raw_event),
    }


def _summarize_reasoning_item(item: ReasoningItem) -> dict[str, Any]:
    raw_item: Any = item.raw_item
    summary: Any = getattr(raw_item, "summary", None)
    content: Any = getattr(raw_item, "content", None)
    summarized: dict[str, Any] = {}
    if summary is not None:
        summarized["summary"] = str(summary)
    if content is not None:
        summarized["content"] = str(content)
    if summarized:
        return summarized
    return {"raw_item": str(raw_item)}


def _summarize_tool_call_item(item: ToolCallItem) -> dict[str, Any]:
    raw_item: Any = item.raw_item
    return {
        "tool_name": str(
            getattr(raw_item, "name", None) or getattr(raw_item, "type", "unknown_tool")
        ),
        "arguments": getattr(raw_item, "arguments", None),
    }


def _summarize_tool_output_item(item: ToolCallOutputItem) -> dict[str, Any]:
    raw_item: Any = item.raw_item
    return {
        "tool_name": str(
            getattr(raw_item, "name", None) or getattr(raw_item, "type", "unknown_tool")
        ),
        "output": item.output,
    }


def _summarize_message_output_item(item: MessageOutputItem) -> dict[str, Any]:
    return {
        "message": ItemHelpers.text_message_output(item),
    }


def _summarize_generic_item(item: Any) -> dict[str, Any]:
    return {
        "item": item,
    }


async def consume_streaming_events(
    result: Any,
    artifacts: RunArtifacts | None = None,
) -> None:
    async for event in result.stream_events():
        if isinstance(event, RawResponsesStreamEvent):
            summary: dict[str, Any] = _summarize_raw_response_event(event.data)
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("raw_llm_event=%s", summary)
            if artifacts is not None:
                artifacts.add_event("raw_response_event", details=summary)
            continue

        if not isinstance(event, RunItemStreamEvent):
            continue

        if event.name == "reasoning_item_created" and isinstance(
            event.item, ReasoningItem
        ):
            summary = _summarize_reasoning_item(event.item)
            logger.debug("llm_reasoning=%s", summary)
            if artifacts is not None:
                artifacts.add_event("reasoning", details=summary)
        elif event.name == "tool_called" and isinstance(event.item, ToolCallItem):
            summary = _summarize_tool_call_item(event.item)
            logger.debug("tool_called=%s", summary)
            if artifacts is not None:
                artifacts.add_event("tool_called", details=summary)
        elif event.name == "tool_output" and isinstance(event.item, ToolCallOutputItem):
            summary = _summarize_tool_output_item(event.item)
            logger.debug("tool_output=%s", summary)
            if artifacts is not None:
                artifacts.add_event("tool_output", details=summary)
        elif event.name == "message_output_created" and isinstance(
            event.item, MessageOutputItem
        ):
            summary = _summarize_message_output_item(event.item)
            logger.debug("message_output=%s", summary)
            if artifacts is not None:
                artifacts.add_event("message_output", details=summary)
        else:
            summary = _summarize_generic_item(event.item)
            logger.debug("agent_event=%s summary=%s", event.name, summary)
            if artifacts is not None:
                artifacts.add_event(event.name, details=summary)
