---
name: sovereign-search
description: Sovereign web search via direct scraping - use when searching the web, researching, fetching URLs, or needing real-time info without API keys. Triggers on search_web, fetch_page, search_and_fetch, web search, research, browse.
---

# Sovereign Search Skill

Use this skill when the user asks to search the web, research a topic, fetch a URL, or needs up-to-date information.

You have **sovereign MCP tools** (no API keys, direct scrape, MCP stdio):

- `search_web(query, count=8, engines="auto")` — returns **clear markdown** with summary table + detailed + JSON block
- `fetch_page(url, max_length=10000, extract_mode="text")` — returns **clear markdown** `# Fetched Content` with source metadata
- `search_and_fetch(query, count=5, fetch_top=2, engines="auto")` — search + direct fetch top results, returns combined markdown
- `list_engines()` — shows 7 sovereign engines

## Engines (all sovereign, no keys)
- `duckduckgo` (html.duckduckgo.com) — most reliable, no JS
- `bing` (bing.com/search + base64 decode)
- `brave`, `mojeek`, `yahoo`, `google` (best-effort), `wikipedia` (open API, no key)

Modes:
- `engines="auto"` → `duckduckgo,bing,wikipedia` (fastest)
- `engines="all"` → all 7 parallel
- `engines="duckduckgo,bing"` → custom

## Markdown Contract
All tools return **markdown** with clear data:
- `search_web` → `# Sovereign Search Results` + `**Query:**` + `## Summary Table` `| # | Title | Engine | URL |` + `## Detailed Results` `### 1. Title` `- **Engine:**` `- **URL:**` `- **Snippet:**` + `<details> JSON`
- `fetch_page` → `# Fetched Content` + `**Source:** [url](url)` + `---` + content
- Always keep markdown, never convert to plain text

## Workflow
1. For research: `search_web(query, count=5, engines="auto")` → pick top URLs → `fetch_page(url)` for full markdown
2. For deep research: `search_and_fetch(query, count=5, fetch_top=2)` — single call
3. Always cite sources with markdown links from results

## Examples
- `search_web(query="MCP Python SDK 2.0 migration", count=5)`
- `search_web(query="Next.js 15 docs", count=3, engines="duckduckgo")`
- `fetch_page(url="https://py.sdk.modelcontextprotocol.io/")`
- `search_and_fetch(query="what is MCP model context protocol", fetch_top=2)`

## Sovereign Notes
- No `TAVILY_API_KEY`/`BRAVE_API_KEY` needed — server implements search itself via `httpx` + `BeautifulSoup` (`mcp-web-search/server.py:132`)
- Rate-limited + cached (`_CACHE_TTL=300`, `_SEMAPHORE=3`) to handle 202 challenges
- MCP stdio JSON-RPC2.0 via FastMCP (`server.py:668`)
