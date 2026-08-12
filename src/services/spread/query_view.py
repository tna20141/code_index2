# Intentions: the repo-frontier inlined-query view -- flatten a repo function's private query-building helpers
# into one coherent, de-indirected query block via `claude -p` (Haiku). On-demand, cached by commit SHA; on
# LLM failure (after claude.py's single retry) fall back to the verbatim body -- spread never hard-fails.
# The derived view sits BESIDE the real body, never replacing it. References: docs/spec.md section 3.

from src.repositories import query_view_cache
from src.utils import claude, git

_PROMPT = """Inline a Python repository-layer function's query-building logic for a code-reading index. The \
function is `{symbol}` at `{location}` (path-from-repo-root:lineno) in the current project.

Why: these query-building/invocation functions are often elaborate -- lots of string manipulation, param \
injection, and private helpers. Inlining and partially resolving them makes the function far easier to \
inspect at a glance.

Do this:
- READ the function yourself from the source. Follow the private query-building helpers it calls (recursively, \
into their files) and inline their contribution.
- Produce ONE coherent, readable version: helpers inlined, redundant indirection cut, the final query \
structure clear. If the function is already simple (no helpers to inline), just return it faithfully.
- PRESERVE the logic exactly. Do NOT invent runtime argument values; do NOT change semantics. If a helper \
cannot be faithfully inlined, leave it as a call with a `# (could not inline: ...)` comment.
- Any remarks you want to add go in CODE COMMENTS, never prose.

OUTPUT CONTRACT (strict -- your output is machine-extracted, so the format MUST be exact):
- Put the ENTIRE inlined function inside ONE markdown code fence annotated `python`:
  ```python
  <the inlined code here>
  ```
- We extract ONLY the content BETWEEN the fences and discard everything outside them.
- A response with NO ```python fenced block is REJECTED and regenerated -- so the fence is mandatory.
- Put ONE fenced block only. Any remarks you want to add go in CODE COMMENTS INSIDE the fence, never as prose."""

# How many times to re-ask the LLM when its output has no extractable ```python block (a well-formed but
# non-conforming response -- distinct from claude.py's process-level retry on invocation failure). After this
# many rejections we fall back to the verbatim body, same as any other generation failure.
_MAX_FENCE_RETRIES = 2


def _extract_fenced(text: str) -> str | None:
    """[Pure] The content of the FIRST ``` fenced block in `text` (language tag line dropped), or None if
    there is no fence. Returning None is the REJECT signal -- the caller retries. Extracting only the fenced
    content also discards any leading prose preamble the model may emit ("Here's the inlined version:")."""
    stripped = text.strip()
    if "```" not in stripped:
        return None
    lines = stripped.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.lstrip().startswith("```"))
    inner = lines[start + 1:]
    end = next((i for i, ln in enumerate(inner) if ln.lstrip().startswith("```")), len(inner))
    return "\n".join(inner[:end]).strip()


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

    prompt = _PROMPT.format(symbol=symbol, location=location)
    content: str | None = None
    # Ask up to (1 + _MAX_FENCE_RETRIES) times for a response with an extractable ```python block. A
    # fence-less reply is well-formed-but-nonconforming, so we re-ask (distinct from claude.py's own
    # process-failure retry, which raises ClaudeInvocationError). Any invocation error -> fall back now.
    for _ in range(1 + _MAX_FENCE_RETRIES):
        try:
            # run the sub-agent IN the project's repo (root_path) so it can read the source; symbol anchors it.
            raw = await claude.run_prompt(prompt, cwd=root_path)
        except claude.ClaudeInvocationError:
            return body  # deterministic fallback -- serve the real body, don't persist a failed view
        content = _extract_fenced(raw)
        if content is not None:
            break
    if content is None:
        return body  # no fenced block after all retries -- fall back rather than cache malformed prose

    await query_view_cache.upsert(
        {"project_id": project_id, "location": location, "content": content,
         "commit_sha": commit_sha, "approved": False})
    return content
