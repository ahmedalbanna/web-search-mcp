"""Sovereign MCP Web Search - pytest suite
Tests clear markdown, no API keys, direct scrape
"""
import asyncio
import sys
sys.path.insert(0, "..")
import pytest

# Add project root
sys.path.insert(0, "/content/mcp-web-search")
import server

# --- Helpers ---

def assert_markdown(txt: str):
    assert isinstance(txt, str)
    assert len(txt) > 20

# --- Unit: helpers ---

def test_clean_text():
    assert server.clean_text("  hello   world  ") == "hello world"
    assert "truncated" in server.clean_text("a"*9000, 100)

def test_normalize_url():
    u = server.normalize_url("https://Example.COM/path/?utm_source=bing&x=1")
    assert "example.com" in u
    assert "utm_source" not in u
    assert "x=1" in u

def test_decode_bing_url():
    # a1 + base64 of https://github.com/modelcontextprotocol/python-sdk
    bing = "https://www.bing.com/ck/a?!&&p=xxx&u=a1aHR0cHM6Ly9naXRodWIuY29tL21vZGVsY29udGV4dHByb3RvY29sL3B5dGhvbi1zZGs"
    assert server.decode_bing_url(bing) == "https://github.com/modelcontextprotocol/python-sdk"

def test_decode_ddg_url():
    ddg = "/l/?kh=-1&uddg=https%3A%2F%2Fexample.com%2Fpath%3Fx%3D1"
    assert server.decode_ddg_url(ddg) == "https://example.com/path?x=1"

def test_engines_registry_sovereign():
    # All engines must be sovereign, no API keys
    assert len(server.ENGINES) >= 7
    for k, v in server.ENGINES.items():
        assert v["sovereign"] is True
        assert "func" in v
    assert "duckduckgo" in server.ENGINES
    assert "bing" in server.ENGINES
    assert "wikipedia" in server.ENGINES

def test_no_api_keys_in_code():
    import pathlib
    text = pathlib.Path("/content/mcp-web-search/server.py").read_text()
    assert "TAVILY" not in text
    assert "SERPER" not in text
    assert "BRAVE_API_KEY" not in text
    assert "API_KEY" not in text or "no API key" in text.lower()

# --- Markdown: search_web ---

@pytest.mark.asyncio
async def test_search_web_markdown_structure():
    txt = await server.search_web("mcp python sdk", count=2, engines="duckduckgo")
    assert_markdown(txt)
    # must be markdown
    if "No Results" not in txt:
        assert "# Sovereign Search Results" in txt
        assert "## Summary Table" in txt
        assert "| # | Title | Engine | URL |" in txt
        assert "## Detailed Results" in txt
        assert "- **Engine:**" in txt
        assert "- **URL:**" in txt
        assert "- **Snippet:**" in txt
        assert "```json" in txt
        assert "Sovereign:" in txt
        assert "sovereign" in txt.lower()
        assert "no api key" in txt.lower()

@pytest.mark.asyncio
async def test_search_web_no_results_markdown():
    txt = await server.search_web("asdlkfjalsdkfjalsdkfj qwertyuiop 123456789 no results expected", count=3, engines="duckduckgo")
    # might be no results or some, but must be markdown either way
    assert_markdown(txt)
    assert txt.startswith("#")

@pytest.mark.asyncio
async def test_search_web_auto_parallel():
    txt = await server.search_web("model context protocol", count=3, engines="auto")
    assert_markdown(txt)
    assert "Sovereign Search Results" in txt or "No Results" in txt

# --- Markdown: fetch_page ---

@pytest.mark.asyncio
async def test_fetch_page_markdown():
    txt = await server.fetch_page("https://example.com", max_length=2000)
    assert_markdown(txt)
    assert "# Fetched Content" in txt or "# Fetch Failed" in txt or "# Fetched:" in txt
    assert "**Source:**" in txt or "**URL:**" in txt or "Example Domain" in txt

@pytest.mark.asyncio
async def test_fetch_page_invalid_url_markdown():
    txt = await server.fetch_page("not-a-url", max_length=1000)
    assert "# Error" in txt
    assert "must start with" in txt

@pytest.mark.asyncio
async def test_fetch_page_html_mode_markdown():
    txt = await server.fetch_page("https://example.com", max_length=2000, extract_mode="html")
    assert "```html" in txt

# --- MCP stdio ---

@pytest.mark.asyncio
async def test_mcp_list_engines_markdown():
    txt = await server.list_engines()
    assert "# Sovereign Search Engines" in txt
    assert "| Engine | Status |" in txt
    assert "duckduckgo" in txt
    assert "Sovereign" in txt

@pytest.mark.asyncio
async def test_mcp_search_and_fetch_markdown():
    txt = await server.search_and_fetch("python programming", count=2, fetch_top=1, engines="duckduckgo")
    assert_markdown(txt)
    # should contain both search and fetched sections if results found
    if "No Results" not in txt:
        assert "Sovereign Search Results" in txt
        # fetched may be present if top results fetched
        assert "Sovereign" in txt

# --- Sovereign fetch unit ---

@pytest.mark.asyncio
async def test_sovereign_fetch():
    txt = await server.sovereign_fetch("https://example.com", 3000)
    assert "Example Domain" in txt

# --- Dedup and cache ---

@pytest.mark.asyncio
async def test_sovereign_search_cache():
    # first call
    res1, _ = await server.sovereign_search("cache test query model context protocol", 2, ["duckduckgo"])
    # second call should be cached and fast
    res2, _ = await server.sovereign_search("cache test query model context protocol", 2, ["duckduckgo"])
    assert res1 == res2

def test_cache_helpers():
    server._cache_set("test:key", [1,2,3])
    assert server._cache_get("test:key") == [1,2,3]
