from __future__ import annotations

import asyncio
import json
import signal
import sys
from typing import Any

from ..commands import CommandRunner
from . import AGENT_PROTOCOL_VERSION
from .adapters import all_adapters, get_adapter
from .base import MODES, AdapterOutcome, AgentRequest, Turn
from .default_agent import resolve_default_agent
from .runner import run_agent
from .storage import ConversationStore

# Only used when test_mode is set (EVERYTHING_AGENT_TEST_MODE=1 or
# --test-mode), so tests/test_agent_protocol.py needs no real agent CLI and
# no network access. Never registered in the real adapter registry.
_TEST_AGENT_NAME = "test-agent"

# Modes that make no sense without at least one allowed folder: "plan" has
# nothing to investigate and "run" would otherwise fall back to whatever
# directory the helper process happens to be started in, silently defeating
# the entire point of the folder-access setting. "ask" needs no filesystem
# access at all, so it alone is exempt.
_MODES_REQUIRING_ALLOWED_DIRS = ("plan", "run")


class AgentJsonLineServer:
    """A second, fully independent JSON-lines helper. Kept deliberately
    separate from everything/server.py: that helper's docs, timeout model,
    and tests are all written around short, local, read-only, unauthenticated
    scans, while a run here is long-running, streamed, cancellable, and
    networked. See docs/agent.md."""

    def __init__(self, *, store: ConversationStore | None = None, test_mode: bool = False) -> None:
        self.test_mode = test_mode
        self.store = store or ConversationStore()
        self.runner = CommandRunner()
        self.output_lock = asyncio.Lock()
        self.tasks: dict[str, asyncio.Task[None]] = {}
        # Tracked separately from self.tasks (which a done callback empties)
        # so a cancellation that raced ahead of the run even starting can
        # still be reported without a conversationId, and one that raced
        # after the conversation was created can still include it.
        self.run_conversation_ids: dict[str, str] = {}
        self.stopping = False

    async def emit(self, message: dict[str, Any]) -> None:
        async with self.output_lock:
            sys.stdout.write(json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n")
            sys.stdout.flush()

    async def run(self) -> int:
        loop = asyncio.get_running_loop()
        adapters = all_adapters()
        capabilities = {
            name: {
                "available": adapter.available(),
                "modes": sorted(adapter.supported_modes),
                **({"unsupportedReason": adapter.unsupported_reason} if not adapter.supported_modes else {}),
            }
            for name, adapter in adapters.items()
        }
        if self.test_mode:
            capabilities[_TEST_AGENT_NAME] = {"available": True, "modes": sorted(MODES)}
        await self.emit({
            "version": AGENT_PROTOCOL_VERSION,
            "type": "ready",
            "capabilities": {"agents": capabilities},
        })

        stop_event = asyncio.Event()

        def stop() -> None:
            self.stopping = True
            stop_event.set()

        for signum in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(signum, stop)
            except NotImplementedError:
                pass

        reader_task = asyncio.create_task(self._read_loop(stop_event), name="agent-json-lines-reader")
        reader_task.add_done_callback(lambda _task: stop_event.set())
        await stop_event.wait()
        self.stopping = True
        reader_task.cancel()
        await asyncio.gather(reader_task, return_exceptions=True)
        for task in list(self.tasks.values()):
            if not task.done():
                task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks.values(), return_exceptions=True)
        return 0

    async def _read_loop(self, stop_event: asyncio.Event) -> None:
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        transport, _ = await asyncio.get_running_loop().connect_read_pipe(lambda: protocol, sys.stdin)
        try:
            while not self.stopping:
                line = await reader.readline()
                if not line:
                    stop_event.set()
                    return
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    await self._protocol_error("", "Malformed JSON request")
                    continue
                if not isinstance(message, dict):
                    await self._protocol_error("", "Request must be a JSON object")
                    continue
                request_id = str(message.get("id") or "")
                if message.get("version") != AGENT_PROTOCOL_VERSION or not request_id:
                    await self._protocol_error(request_id, "Unsupported protocol version or missing request id")
                    continue
                request_type = str(message.get("type") or "")
                if request_type == "agentRun":
                    task = asyncio.create_task(self._handle_run(request_id, message), name=f"agent-run:{request_id}")
                    self.tasks[request_id] = task
                    task.add_done_callback(lambda finished, rid=request_id: self._on_run_task_done(rid, finished))
                elif request_type == "agentCancel":
                    target = str(message.get("requestId") or "")
                    running = self.tasks.get(target)
                    if running and not running.done():
                        running.cancel()
                elif request_type == "agentConversationList":
                    await self._handle_list(request_id)
                elif request_type == "agentConversationGet":
                    await self._handle_get(request_id, str(message.get("conversationId") or ""))
                elif request_type == "agentConversationDelete":
                    await self._handle_delete(request_id, str(message.get("conversationId") or ""))
                elif request_type == "shutdown":
                    stop_event.set()
                    return
                else:
                    await self._protocol_error(request_id, f"Unknown request type: {request_type}")
        finally:
            transport.close()

    async def _protocol_error(self, request_id: str, message: str) -> None:
        await self.emit({
            "version": AGENT_PROTOCOL_VERSION,
            "type": "error",
            "requestId": request_id,
            "message": message,
            "nonfatal": True,
        })

    async def _run_failed(self, request_id: str, conversation_id: str, message: str) -> None:
        await self.emit({
            "version": AGENT_PROTOCOL_VERSION,
            "type": "agentRunFailed",
            "requestId": request_id,
            "conversationId": conversation_id,
            "message": message,
        })

    async def _handle_run(self, request_id: str, message: dict[str, Any]) -> None:
        mode = str(message.get("mode") or "")
        prompt = str(message.get("prompt") or "").strip()
        allowed_dirs = tuple(
            str(value) for value in (message.get("allowedDirs") or []) if isinstance(value, str) and value
        )
        conversation_id = str(message.get("conversationId") or "")
        requested_agent = str(message.get("agent") or "")

        if mode not in MODES:
            await self._run_failed(request_id, conversation_id, f"Unknown mode: {mode or '(empty)'}")
            return
        if not prompt:
            await self._run_failed(request_id, conversation_id, "Prompt must not be empty")
            return
        if mode in _MODES_REQUIRING_ALLOWED_DIRS and not allowed_dirs:
            await self._run_failed(request_id, conversation_id, f"{mode} mode requires at least one allowed folder")
            return

        if self.test_mode:
            agent_name = requested_agent or _TEST_AGENT_NAME
        else:
            agent_name = requested_agent or await resolve_default_agent(self.runner)
        if not agent_name:
            await self._run_failed(
                request_id, conversation_id,
                "No default agent is configured. Set one with: omarchy default agent <name>",
            )
            return
        adapter = None if agent_name == _TEST_AGENT_NAME else get_adapter(agent_name)
        if adapter is None and agent_name != _TEST_AGENT_NAME:
            await self._run_failed(request_id, conversation_id, f"Unknown or unsupported agent: {agent_name}")
            return

        conversation = self.store.get(conversation_id) if conversation_id else None
        if conversation is None:
            conversation = self.store.create(agent_name, mode, allowed_dirs)
        conversation_id = conversation.id
        # Recorded so a cancellation racing in right after this point can
        # still report the right conversationId even though self.tasks (and
        # this coroutine's own frame) may already be gone by then.
        self.run_conversation_ids[request_id] = conversation_id
        resume_session_id = str(message.get("resumeSessionId") or "") or conversation.provider_session_id

        self.store.append_turn(conversation_id, Turn("user", prompt))

        request = AgentRequest(
            agent=agent_name,
            mode=mode,
            prompt=prompt,
            allowed_dirs=allowed_dirs,
            resume_session_id=resume_session_id,
            conversation_id=conversation_id,
        )

        async def on_turn(turn: Turn) -> None:
            self.store.append_turn(conversation_id, turn)
            await self.emit({
                "version": AGENT_PROTOCOL_VERSION,
                "type": "agentTurn",
                "requestId": request_id,
                "conversationId": conversation_id,
                "turn": turn.to_json(),
                "final": False,
            })

        # No except-CancelledError here: a cancel racing in before this task
        # ever got its first turn on the event loop can throw the exception
        # in before *any* of this function's body — including this try block
        # — has executed, so a handler placed here is not reliably reached.
        # _on_run_task_done, driven by the task's own done-callback, is the
        # single place that guarantees a terminal message for every
        # cancellation, regardless of when it lands.
        if agent_name == _TEST_AGENT_NAME:
            outcome = await self._fake_run(request, on_turn)
        else:
            outcome = await run_agent(self.runner, adapter, request, on_turn)

        for turn in outcome.turns:
            await on_turn(turn)
        if outcome.provider_session_id:
            self.store.set_provider_session_id(conversation_id, outcome.provider_session_id)

        await self.emit({
            "version": AGENT_PROTOCOL_VERSION,
            "type": "agentTurn",
            "requestId": request_id,
            "conversationId": conversation_id,
            "final": True,
            "ok": outcome.ok,
            **({"message": outcome.error_message} if not outcome.ok and outcome.error_message else {}),
        })

    def _on_run_task_done(self, request_id: str, finished: "asyncio.Task[None]") -> None:
        self.tasks.pop(request_id, None)
        conversation_id = self.run_conversation_ids.pop(request_id, "")
        if finished.cancelled():
            asyncio.create_task(self.emit({
                "version": AGENT_PROTOCOL_VERSION,
                "type": "agentTurn",
                "requestId": request_id,
                "conversationId": conversation_id,
                "final": True,
                "ok": False,
                "cancelled": True,
            }))
            return
        error = finished.exception()
        if error is not None:
            # A bug elsewhere in _handle_run, not a normal adapter failure
            # (those already produce a clean final:false outcome). Still
            # terminate the request instead of leaving the client hanging.
            asyncio.create_task(self.emit({
                "version": AGENT_PROTOCOL_VERSION,
                "type": "agentTurn",
                "requestId": request_id,
                "conversationId": conversation_id,
                "final": True,
                "ok": False,
                "message": str(error),
            }))

    async def _fake_run(self, request: AgentRequest, on_turn) -> AdapterOutcome:
        # A deliberately trivial, deterministic stand-in for a real agent
        # CLI: no subprocess, no network. "fail" as the whole prompt exercises
        # the agentRunFailed-shaped failure path from the client side too.
        if request.prompt.strip().lower() == "fail":
            return AdapterOutcome(ok=False, error_message="synthetic failure for testing")
        await on_turn(Turn("assistant", f"[{request.mode}] echo: {request.prompt}"))
        return AdapterOutcome(ok=True, provider_session_id="test-session-1")

    async def _handle_list(self, request_id: str) -> None:
        summaries = [summary.to_json() for summary in self.store.list_conversations()]
        await self.emit({
            "version": AGENT_PROTOCOL_VERSION,
            "type": "agentConversationList",
            "requestId": request_id,
            "conversations": summaries,
        })

    async def _handle_get(self, request_id: str, conversation_id: str) -> None:
        conversation = self.store.get(conversation_id) if conversation_id else None
        if conversation is None:
            await self._protocol_error(request_id, "Unknown conversation")
            return
        await self.emit({
            "version": AGENT_PROTOCOL_VERSION,
            "type": "agentConversationGet",
            "requestId": request_id,
            "conversationId": conversation.id,
            "agent": conversation.agent,
            "mode": conversation.mode,
            "turns": [turn.to_json() for turn in conversation.turns],
        })

    async def _handle_delete(self, request_id: str, conversation_id: str) -> None:
        ok = self.store.delete(conversation_id) if conversation_id else False
        await self.emit({
            "version": AGENT_PROTOCOL_VERSION,
            "type": "agentConversationDelete",
            "requestId": request_id,
            "conversationId": conversation_id,
            "ok": ok,
        })
