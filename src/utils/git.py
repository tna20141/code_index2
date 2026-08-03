# Intentions: read-only git queries against an indexed repo. `root_path` is the repo dir (the active
# project's root, from the project registry -- one server serves many repos). Used by the query-view cache
# (current commit for keying) and the scanning agent's diff base. No writes, ever.

import asyncio


async def _run(root_path: str, *args: str) -> str:
    proc = await asyncio.create_subprocess_exec(
        "git", "-C", root_path, *args,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {stderr.decode().strip()}")
    return stdout.decode().strip()


async def get_head(root_path: str) -> str:
    """Current HEAD commit sha of the repo at `root_path`."""
    return await _run(root_path, "rev-parse", "HEAD")


async def diff_names(root_path: str, base: str) -> list[str]:
    """Paths (relative to root_path) changed between `base` and HEAD -- the scanning agent's work list."""
    out = await _run(root_path, "diff", "--name-only", base, "HEAD")
    return [line for line in out.splitlines() if line]
