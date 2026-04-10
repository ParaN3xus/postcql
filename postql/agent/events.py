from __future__ import annotations

from typing import Any

from agents import (
    ItemHelpers,
    MessageOutputItem,
    ReasoningItem,
    RunItemStreamEvent,
    ToolCallItem,
    ToolCallOutputItem,
)

from ..logging import logger
from ..run_artifacts import RunArtifacts


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
    summary: dict[str, Any] = {
        "tool_name": str(
            getattr(raw_item, "name", None) or getattr(raw_item, "type", "unknown_tool")
        ),
        "arguments": getattr(raw_item, "arguments", None),
    }
    call_id: Any = getattr(raw_item, "call_id", None)
    if isinstance(call_id, str):
        summary["call_id"] = call_id
    return summary


def _summarize_tool_output_item(item: ToolCallOutputItem) -> dict[str, Any]:
    raw_item: Any = item.raw_item
    tool_name: str = str(
        getattr(raw_item, "name", None) or getattr(raw_item, "type", "unknown_tool")
    )
    call_id: Any = getattr(raw_item, "call_id", None)
    if isinstance(raw_item, dict):
        tool_name = str(raw_item.get("name") or raw_item.get("type") or tool_name)
        call_id = raw_item.get("call_id", call_id)

    summary: dict[str, Any] = {
        "tool_name": tool_name,
        "output": item.output,
    }
    if isinstance(call_id, str):
        summary["call_id"] = call_id
    return summary


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
    tool_names_by_call_id: dict[str, str] = {}
    final_message_output: str | None = None

    async for event in result.stream_events():
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
            call_id: Any = summary.get("call_id")
            tool_name: Any = summary.get("tool_name")
            if isinstance(call_id, str) and isinstance(tool_name, str):
                tool_names_by_call_id[call_id] = tool_name
            logger.debug("tool_called=%s", summary)
            if artifacts is not None:
                artifacts.add_event("tool_called", details=summary)
        elif event.name == "tool_output" and isinstance(event.item, ToolCallOutputItem):
            summary = _summarize_tool_output_item(event.item)
            call_id = summary.get("call_id")
            if isinstance(call_id, str) and call_id in tool_names_by_call_id:
                summary["tool_name"] = tool_names_by_call_id[call_id]
            logger.debug("tool_output=%s", summary)
            if artifacts is not None:
                artifacts.add_event("tool_output", details=summary)
        elif event.name == "message_output_created" and isinstance(
            event.item, MessageOutputItem
        ):
            summary = _summarize_message_output_item(event.item)
            logger.debug("message_output=%s", summary)
            final_message_output = str(summary["message"])
        else:
            summary = _summarize_generic_item(event.item)
            logger.debug("agent_event=%s summary=%s", event.name, summary)
            if artifacts is not None:
                artifacts.add_event(event.name, details=summary)

    if artifacts is not None and final_message_output is not None:
        artifacts.add_event(
            "final_output",
            details={"message": final_message_output},
        )
