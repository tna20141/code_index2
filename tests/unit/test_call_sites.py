# Unit tests for the ast-based call-site extraction in spread (_call_sites). Verifies it finds the callee
# token's file line/col for both plain Name calls and Attribute (method) calls, over a nested (indented) body.

from src.services.spread import _call_sites


def test_finds_name_calls_with_file_coordinates():
    # a dedented function body; base_line = the file line of body[0].
    body = [
        "def outer():",
        "    x = helper(1)",
        "    return other(x)",
    ]
    sites = _call_sites(body, base_line=10)
    names = {name for _, _, name in sites}
    assert names == {"helper", "other"}
    # helper is on body line 2 -> file line 11; column points at 'helper'
    helper = next(s for s in sites if s[2] == "helper")
    assert helper[0] == 11
    assert body[1][helper[1] - 1:].startswith("helper")


def test_finds_attribute_calls_on_rightmost_token():
    body = [
        "async def outer():",
        "    return await repo.find_by_id(tenant, id)",
    ]
    sites = _call_sites(body, base_line=5)
    assert any(name == "find_by_id" for _, _, name in sites)
    site = next(s for s in sites if s[2] == "find_by_id")
    assert body[site[0] - 5][site[1] - 1:].startswith("find_by_id")


def test_non_parseable_fragment_yields_no_sites():
    assert _call_sites(["def broken(:", "  pass"], base_line=1) == []


def test_empty_body():
    assert _call_sites([], base_line=1) == []
