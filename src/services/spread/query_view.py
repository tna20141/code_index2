# Intentions: the repo-frontier inlined-query view -- flatten a repo function's private query-building helpers
# into one coherent, de-indirected query block via `claude -p` (Haiku). On-demand, cached by commit SHA; on
# LLM failure (after claude.py's single retry) fall back to the verbatim body -- spread never hard-fails.
# The derived view sits BESIDE the real body, never replacing it. References: docs/spec.md section 3.

from src.repositories import query_view_cache
from src.utils import claude, git

_PROMPT = """You are inlining a Python repository-layer function's query-building logic for a code-reading \
index. The function is `{symbol}` at `{location}` (path-from-repo-root:lineno) in the current project -- READ \
it yourself from the source, read the private query-building helpers it calls recursively (follow them into their \
files) so you can inline their contribution. Produce ONE coherent, readable version of the function it builds: \
inline those helpers, cut redundant indirection, and make the final query structure clear. PRESERVE the logic \
exactly -- do NOT invent runtime argument values, do NOT change semantics. If any helper cannot be faithfully \
inlined, leave it as a call and note it with a `# (could not inline: ...)` comment. Output only the inlined \
code block, no prose. The reason you exists is that a query building and invocation function is often quite \
elaborate with a lot of string manipulation and param injection. Your inlining and partial resolving will help \
inspecting these functions easier. But make sure the logic is accurate and complete though. And remember, the \
output is inserted verbatim somewhere so skip prose/preamble etc. Only output the raw final result, with \
proper code formatting and indentation (no code fences). Anything you wanna add should be in the form of \
code comments."""

async def get_or_generate(project_id: str, root_path: str, location: str, body: str,
                          symbol: str = "") -> str:
    """The inlined-query view for a repo-frontier function at `location` in `project_id`. The claude -p
    sub-agent reads the function + its helpers from source itself (it runs server-side, co-located with the
    repo); `symbol` is the callee's name (from the call site) used as the prompt anchor, `body` is the
    verbatim fallback if generation fails. `root_path` -> the repo dir for the commit sha. Cache hit (this
    project's location AT the current commit) -> serve it. Miss -> `claude -p` (retry once inside
    claude.run_prompt); on failure fall back to `body`. Regeneration stores approved=False."""
    commit_sha = await git.get_head(root_path)
    cached = await query_view_cache.get(project_id, location, commit_sha)
    if cached is not None:
        return cached["content"]

    try:
        # prefer the call-site name (the invoked name); fall back to parsing the def line.
        content = await claude.run_prompt(_PROMPT.format(symbol=symbol, location=location))
    except claude.ClaudeInvocationError:
        return body  # deterministic fallback -- serve the real body, don't persist a failed view

    await query_view_cache.upsert(
        {"project_id": project_id, "location": location, "content": content,
         "commit_sha": commit_sha, "approved": False})
    return content
