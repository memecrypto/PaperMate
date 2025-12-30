import json
import asyncio
import logging
import re
from typing import Any, Callable, Awaitable, Sequence

from openai import AsyncOpenAI, APIConnectionError, RateLimitError, APIStatusError

from app.core.config import get_settings
from app.services.tools import BaseTool

settings = get_settings()
logger = logging.getLogger(__name__)

MAX_RETRIES = 5
INITIAL_RETRY_DELAY = 1.0

ProgressCallback = Callable[[dict], Awaitable[None]]

_TOOLING_ERROR_HINTS = (
    "tools",
    "tool_choice",
    "tool_calls",
    "function calling",
    "function_call",
    "functions",
    "unknown parameter",
    "unsupported",
)


def _extract_final_from_reasoning(reasoning: str) -> str:
    if not reasoning:
        return ""
    match = re.search(r"(?is)<final[^>]*>(.*?)</final>", reasoning)
    if match:
        return match.group(1).strip()
    match = re.search(
        r"(?:最终答案|最终输出|答案|Final Answer|Final|Answer)\s*[:：]\s*([\s\S]+)$",
        reasoning,
        re.I,
    )
    if match:
        return match.group(1).strip()
    return ""


def _extract_content_from_message(msg: Any) -> str:
    content = getattr(msg, "content", None)
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
                continue
            if isinstance(part, dict):
                text = part.get("text") or part.get("content") or part.get("value")
                if text is not None:
                    parts.append(str(text))
                continue
            text = getattr(part, "text", None) or getattr(part, "content", None) or getattr(part, "value", None)
            if text is not None:
                parts.append(str(text))
        content = "".join(parts)
    if isinstance(content, str):
        text = content.strip()
        if text:
            return text
    reasoning = getattr(msg, "reasoning_content", None)
    if isinstance(reasoning, str) and reasoning.strip():
        return _extract_final_from_reasoning(reasoning)
    return ""


def _extract_content_from_completion(completion: Any) -> str:
    try:
        choice = completion.choices[0]
    except Exception:
        return ""
    message = getattr(choice, "message", None)
    if message is not None:
        content = _extract_content_from_message(message)
        if content:
            return content
    try:
        raw = completion.model_dump()
    except Exception:
        raw = {}
    choices = raw.get("choices") or []
    if not choices:
        return ""
    msg = choices[0].get("message") or {}
    content = msg.get("content") or choices[0].get("text") or ""
    if not content and msg.get("reasoning_content"):
        content = _extract_final_from_reasoning(str(msg.get("reasoning_content")))
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
                continue
            if isinstance(part, dict):
                text = part.get("text") or part.get("content") or part.get("value")
                if text is not None:
                    parts.append(str(text))
                continue
            text = getattr(part, "text", None) or getattr(part, "content", None) or getattr(part, "value", None)
            if text is not None:
                parts.append(str(text))
        content = "".join(parts)
    if isinstance(content, str):
        return content.strip()
    return ""


class ReActAgent:
    """ReAct-style agent using OpenAI function calling for tool invocation."""

    def __init__(
        self,
        client: AsyncOpenAI,
        tools: Sequence[BaseTool],
        model: str | None = None,
        max_steps: int = 6,
        temperature: float = 0.2,
        tool_output_limit: int = 4000,
        max_tool_messages: int = 8,
        on_progress: ProgressCallback | None = None,
        disable_tools: bool = False,
    ):
        self.client = client
        self.model = model or settings.openai_model
        self.max_steps = max_steps
        self.temperature = temperature
        self.tool_output_limit = tool_output_limit
        self.max_tool_messages = max_tool_messages
        self.tools = {t.name: t for t in tools}
        self.tool_specs = [t.openai_spec() for t in tools] if tools else []
        self.on_progress = on_progress
        self.disable_tools = disable_tools
        self._force_disable_tools = False

    async def _emit(self, event: dict) -> None:
        if self.on_progress:
            try:
                await self.on_progress(event)
            except Exception:
                pass

    def _should_use_tools(self) -> bool:
        return bool(self.tool_specs) and not self.disable_tools and not self._force_disable_tools

    def _is_tooling_incompatibility_error(self, e: Exception) -> bool:
        text = str(e).lower()
        if any(h in text for h in _TOOLING_ERROR_HINTS):
            return True
        if isinstance(e, APIStatusError) and getattr(e, "status_code", None) in (400, 404, 422):
            return True
        return False

    async def _create_completion(
        self,
        messages: list[dict[str, Any]],
        max_tokens: int | None,
        use_tools: bool,
    ) -> Any:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if use_tools and self.tool_specs:
            kwargs["tools"] = self.tool_specs
            kwargs["tool_choice"] = "auto"
        return await self.client.chat.completions.create(**kwargs)

    async def _call_llm_with_retry(
        self, messages: list[dict[str, Any]], max_tokens: int | None, step: int
    ) -> Any | None:
        """Call LLM with exponential backoff retry for connection errors and rate limits."""
        delay = INITIAL_RETRY_DELAY
        use_tools = self._should_use_tools()

        for attempt in range(MAX_RETRIES):
            try:
                logger.debug(
                    "ReActAgent step %s/%s calling LLM (attempt %s/%s) use_tools=%s model=%s",
                    step + 1, self.max_steps, attempt + 1, MAX_RETRIES, use_tools, self.model,
                )
                try:
                    return await self._create_completion(messages, max_tokens, use_tools=use_tools)
                except Exception as e:
                    if use_tools and self._is_tooling_incompatibility_error(e):
                        self._force_disable_tools = True
                        logger.warning(
                            "ReActAgent disabling tools due to provider/model incompatibility: %s", str(e)[:200],
                        )
                        use_tools = False
                        return await self._create_completion(messages, max_tokens, use_tools=False)
                    raise
            except (APIConnectionError, RateLimitError) as e:
                if attempt < MAX_RETRIES - 1:
                    logger.warning(
                        f"ReActAgent LLM call failed (attempt {attempt+1}/{MAX_RETRIES}): {type(e).__name__}. "
                        f"Retrying in {delay:.1f}s..."
                    )
                    await asyncio.sleep(delay)
                    delay *= 2
                else:
                    logger.error(f"ReActAgent LLM call failed after {MAX_RETRIES} attempts: {e}")
                    return None
            except APIStatusError as e:
                if e.status_code == 429:
                    if attempt < MAX_RETRIES - 1:
                        logger.warning(
                            f"ReActAgent rate limited (attempt {attempt+1}/{MAX_RETRIES}). "
                            f"Retrying in {delay:.1f}s..."
                        )
                        await asyncio.sleep(delay)
                        delay *= 2
                    else:
                        logger.error(f"ReActAgent rate limited after {MAX_RETRIES} attempts")
                        return None
                else:
                    logger.warning(f"ReActAgent LLM call failed at step {step}: {e}", exc_info=True)
                    return None
            except Exception as e:
                logger.warning(f"ReActAgent LLM call failed at step {step}: {e}", exc_info=True)
                return None

        return None

    async def run(
        self,
        system_prompt: str,
        user_prompt: str | list[dict[str, Any]],
        max_tokens: int | None = None,
    ) -> str:
        """Run the agent. user_prompt can be a string or multimodal content list."""
        user_content = user_prompt if isinstance(user_prompt, list) else user_prompt
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        logger.info(
            "ReActAgent starting model=%s tools=%s disable_tools=%s",
            self.model,
            [t["function"]["name"] for t in self.tool_specs],
            self.disable_tools,
        )

        # If tools disabled or not available, just do a single completion
        if not self._should_use_tools():
            completion = await self._call_llm_with_retry(messages, max_tokens, step=0)
            if completion is None:
                return ""
            return _extract_content_from_completion(completion)

        for step in range(self.max_steps):
            messages = self._trim_tool_messages(messages)

            completion = await self._call_llm_with_retry(messages, max_tokens, step)
            if completion is None:
                break

            msg = completion.choices[0].message
            tool_calls = getattr(msg, "tool_calls", None)

            if tool_calls:
                logger.info(f"ReActAgent step {step+1}: model requested {len(tool_calls)} tool calls: {[tc.function.name for tc in tool_calls]}")
                messages.append(self._message_to_dict(msg))
                tool_results = await self._execute_tool_calls(tool_calls)
                messages.extend(tool_results)
                continue

            content = _extract_content_from_message(msg)
            if not content:
                content = _extract_content_from_completion(completion)
            if content:
                logger.info(f"ReActAgent completed at step {step+1} with {len(content)} chars output")
                return content

            logger.warning(f"ReActAgent step {step+1}: empty response, breaking")
            break

        # If we broke out of loop without a response (e.g., model returned empty after tool calls),
        # try one more time without tools using just the original prompt
        logger.info("ReActAgent final fallback: retrying without tools")
        fallback_messages = [
            {"role": "system", "content": messages[0]["content"]},
            {"role": "user", "content": messages[1]["content"]},
        ]
        self._force_disable_tools = True
        completion = await self._call_llm_with_retry(fallback_messages, max_tokens, step=0)
        if completion is not None:
            content = _extract_content_from_completion(completion)
            if content:
                logger.info("ReActAgent fallback succeeded with %d chars", len(content))
                return content

        for m in reversed(messages):
            if m.get("role") == "assistant" and m.get("content"):
                return str(m["content"]).strip()

        return ""

    def _trim_tool_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Keep only the most recent tool messages to prevent context overflow."""
        tool_indices = [i for i, m in enumerate(messages) if m.get("role") == "tool"]
        if len(tool_indices) <= self.max_tool_messages:
            return messages

        keep_from = tool_indices[-self.max_tool_messages]
        non_tool = [m for m in messages[:keep_from] if m.get("role") != "tool"]
        recent = messages[keep_from:]
        return non_tool + recent

    def _message_to_dict(self, msg: Any) -> dict[str, Any]:
        tool_calls = getattr(msg, "tool_calls", None) or []
        assistant_msg: dict[str, Any] = {"role": "assistant"}
        if tool_calls:
            assistant_msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in tool_calls
            ]
            if msg.content:
                assistant_msg["content"] = msg.content
            return assistant_msg

        assistant_msg["content"] = msg.content or ""
        return assistant_msg

    async def _execute_tool_calls(self, tool_calls: Sequence[Any]) -> list[dict[str, Any]]:
        tool_messages: list[dict[str, Any]] = []

        for tc in tool_calls:
            name = getattr(tc.function, "name", "unknown")
            args_text = getattr(tc.function, "arguments", "{}")

            try:
                args = json.loads(args_text)
                query = str(args.get("query") or args.get("q") or "")[:100]
            except Exception:
                query = args_text[:100] if args_text else ""

            await self._emit({
                "type": "tool_call",
                "tool": name,
                "query": query,
                "status": "calling",
            })

            result = await self._run_single_tool(tc)
            result_count = result.count("Title:") or result.count("- ") or (1 if result and "error" not in result.lower() else 0)

            await self._emit({
                "type": "tool_call",
                "tool": name,
                "query": query,
                "status": "done",
                "result_count": result_count,
            })

            content = str(result)
            if len(content) > self.tool_output_limit:
                content = content[: self.tool_output_limit] + "\n...[truncated]"

            tool_messages.append({
                "role": "tool",
                "tool_call_id": getattr(tc, "id", ""),
                "content": content,
            })

        return tool_messages

    async def _run_single_tool(self, tool_call: Any) -> str:
        try:
            name = tool_call.function.name
            args_text = tool_call.function.arguments or "{}"
        except Exception:
            return "Invalid tool call format."

        try:
            args = json.loads(args_text)
        except Exception:
            args = {"query": args_text}

        tool = self.tools.get(name)
        if not tool:
            return f"Unknown tool: {name}"

        try:
            # Pass full args dict to tool - tools can handle both dict and string
            return await tool.execute(args)
        except Exception as e:
            logger.warning(f"Tool {name} execution failed", exc_info=True)
            return f"Tool execution error: {e}"
