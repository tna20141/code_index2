# Intentions: one-shot `claude -p` invocation for the query-view inlining (repo-frontier). Retry once,
# then let the caller fall back to deterministic. Kept as a util so the resolver/query-view logic stays
# clean of subprocess plumbing.
#
# `cwd` is REQUIRED to be the INDEXED PROJECT's root: the prompt asks the sub-agent to read the function and
# its helpers from source, so it must run IN that repo -- not in the MCP server's own directory (else its
# file tools see code_index2's files, not the target codebase's).

import asyncio

from src.config import settings


class ClaudeInvocationError(RuntimeError):
    """`claude -p` failed after the retry -- the caller falls back to the verbatim body."""


async def _invoke_once(prompt: str, model: str, cwd: str) -> str:
    proc = await asyncio.create_subprocess_exec(
        settings.claude_bin, "-p", prompt, "--model", model,
        cwd=cwd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise ClaudeInvocationError(f"claude -p exited {proc.returncode}: {stderr.decode().strip()}")
    return stdout.decode().strip()


async def run_prompt(prompt: str, cwd: str, model: str | None = None) -> str:
    """Run `claude -p <prompt>` WITH `cwd` as the working dir (the indexed project's root, so the sub-agent's
    file tools see the target codebase). On failure retry ONCE, then raise ClaudeInvocationError. The
    query-view caller catches that and serves the verbatim body (spread never hard-fails on LLM trouble)."""
    chosen_model = model or settings.claude_query_view_model
    try:
        return await _invoke_once(prompt, chosen_model, cwd)
    except ClaudeInvocationError:
        return await _invoke_once(prompt, chosen_model, cwd)  # single retry; a second failure propagates
