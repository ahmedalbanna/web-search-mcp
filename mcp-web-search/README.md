# Sovereign MCP Web Search Server

**No API keys. No external company. No monopoly.**

Directly scrapes search engines via HTTP + HTML parsing. Your server owns the entire search process. Communicates directly via MCP stdio (JSON-RPC 2.0) with FastMCP.

## Sovereign Architecture

```
Your Agent <--(MCP stdio JSON-RPC 2.0)--> Sovereign Server --(direct HTTPS)--> Search Engines
                                              |
                                              +-> html.duckduckgo.com  (primary)
                                              +-> www.bing.com         (reliable)
                                              +-> search.brave.com     (independent index)
                                              +-> www.mojeek.com       (independent UK)
                                              +-> search.yahoo.com     (fallback)
                                              +-> www.google.com       (best-effort)
                                              +-> en.wikipedia.org     (open API, no key)
                                              +-> direct fetch (any URL) via httpx + BeautifulSoup
```

- **No Tavily / Serper / Brave API keys**
- **No `ddgs` package dependency**
- **No external search proxy** — you implement the search process yourself
- **All engines scraped in parallel, deduplicated, ranked sovereignly**

## MCP Tools (direct stdio)

| Tool | Description |
|------|-------------|
| `search_web(query, count=8, engines="auto")` | Sovereign search across engines |
| `fetch_page(url, max_length=10000, extract_mode="text")` | Sovereign direct fetch + readability |
| `search_and_fetch(query, count=5, fetch_top=2, engines="auto")` | Search + auto-fetch top results |
| `list_engines()` | List all sovereign engines |

### Engines

| Engine | Sovereign | Method | Reliability |
|--------|-----------|--------|-------------|
| `duckduckgo` | ✅ | `POST html.duckduckgo.com/html/` + BS4 | ⭐⭐⭐⭐⭐ No JS, most reliable |
| `bing` | ✅ | `GET bing.com/search` + base64 decode | ⭐⭐⭐⭐ Server-rendered |
| `brave` | ✅ | `GET search.brave.com/search` + BS4 | ⭐⭐⭐ Independent, may 429 in cloud |
| `mojeek` | ✅ | `GET mojeek.com/search` + BS4 | ⭐⭐⭐ Independent UK index |
| `yahoo` | ✅ | `GET search.yahoo.com/search` + BS4 | ⭐⭐ Fallback |
| `google` | ✅ | `GET google.com/search` + BS4 | ⭐⭐ Best-effort, often JS-blocked |
| `wikipedia` | ✅ | `GET wikipedia.org/w/api.php` (open, no key) | ⭐⭐ Encyclopedic, may 403 in datacenter* |

\* Wikipedia blocks some datacenter IPs. Works sovereignly from your local machine. Auto-mode falls back to DDG/Bing gracefully.

**Modes:**
- `engines="auto"` → `duckduckgo,bing,wikipedia` (recommended, fastest, parallel)
- `engines="all"` → all 7 in parallel (best coverage, slower)
- `engines="duckduckgo,bing"` → custom comma list

### Fetch

`fetch_page` is also sovereign: `httpx` + `BeautifulSoup` readability, no `jina.ai` or `tavily extract`.

- Strips scripts, nav, footer
- Prioritizes `main`/`article`
- Preserves headings

## Quick Start (Sovereign)

```bash
pip install -e .
# deps: mcp, httpx, beautifulsoup4, lxml (no ddgs, no api keys)

# Run sovereign MCP server (stdio)
python server.py

# Test via MCP inspector
# search then fetch
```

Test via Python MCP client:
```python
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

params = StdioServerParameters(command="python", args=["/content/mcp-web-search/server.py"])
async with stdio_client(params) as (read, write):
    async with ClientSession(read, write) as session:
        await session.initialize()
        r = await session.call_tool("search_web", arguments={"query": "sovereign MCP server python", "count": 5})
        print(r.content[0].text)
```

## OpenCode Config (Direct MCP)

Add to `opencode.json` (project) or `~/.config/opencode/opencode.json` (global):

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "web-search": {
      "type": "local",
      "command": ["python", "/content/mcp-web-search/server.py"],
      "enabled": true
    }
  }
}
```

No `environment` keys needed — sovereign needs no keys.

For `uv`:

```json
{
  "mcp": {
    "web-search": {
      "type": "local",
      "command": ["uv", "run", "/content/mcp-web-search/server.py"],
      "enabled": true
    }
  }
}
```

Then **quit and restart opencode** (config loads at startup).

## Examples for Agent

- `search_web(query="Next.js 15 docs 2026", engines="auto")`
- `search_web(query="rust MCP SDK", count=3, engines="duckduckgo")`
- `search_web(query="open source search engine", count=5, engines="all")`
- `fetch_page(url="https://modelcontextprotocol.io/docs/getting-started/intro")`
- `search_and_fetch(query="what is MCP model context protocol", fetch_top=2, engines="duckduckgo,bing")`
- `list_engines()`

## How It Implements Search (Sovereign)

1. **Parallel scrape**: `asyncio.gather` queries 2-7 engines at once
2. **Per-engine parser**: each engine has dedicated `scrape_*` with engine-specific CSS selectors
3. **Bot evasion**: random `User-Agent` rotation, proper `Referer`, `Accept-Language`
4. **Decode**: Bing `u=a1aHR0...` base64, DuckDuckGo `uddg=` unquote
5. **Filter**: ads (`y.js`, `aclick`) filtered
6. **Deduplicate**: `normalize_url` + `seen` set across engines, round-robin interleaving
7. **MCP**: `FastMCP` exposes tools via stdio JSON-RPC 2.0 — no HTTP server, no proxy

See `server.py:132` `scrape_duckduckgo`, `server.py:179` `scrape_bing`, `server.py:376` `scrape_wikipedia`, `server.py:418` `sovereign_fetch`, `server.py:490` `sovereign_search`, `server.py:530` `search_web` tool.

## Verify Sovereign (No Keys)

```bash
env | grep -i API_KEY  # should be empty - sovereign needs none
grep -r "API_KEY" server.py  # should be empty
grep -r "TAVILY\|SERPER\|BRAVE_API" server.py  # empty - sovereign
```

