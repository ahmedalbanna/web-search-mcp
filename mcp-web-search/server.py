#!/usr/bin/env python3
"""
SOVEREIGN MCP Web Search Server
No API keys. No external company dependency.
Directly scrapes search engines via HTTP + HTML parsing.
Communicates via MCP stdio (JSON-RPC 2.0).

Engines implemented (all direct, no key):
 - duckduckgo  : html.duckduckgo.com/html/  (Primary, most reliable, no JS)
 - bing        : www.bing.com/search        (Reliable, needs redirect decode)
 - brave      : search.brave.com/search     (Independent index, may 429 in cloud)
 - mojeek     : www.mojeek.com/search       (Independent UK index)
 - yahoo      : search.yahoo.com/search     (Fallback)
 - google     : www.google.com/search       (May require JS, best-effort)
 - wikipedia  : en.wikipedia.org/w/api.php  (No scraping, open API, no key - sovereign)
 - searx      : searx.be/search (demo, optional)

All engines are scraped in parallel for "auto" / "all" mode, deduplicated by URL.
Fetch is also sovereign: direct httpx + BeautifulSoup readability extraction.

MCP Tools:
 - search_web(query, count=8, engines="auto")
 - fetch_page(url, max_length=10000)
 - search_and_fetch(query, count=5, fetch_top=2, engines="auto")
 - list_engines()
"""

import re
import asyncio
import base64
import random
import urllib.parse
import json
from typing import Any, Optional

import httpx
try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    try:
        from fastmcp import FastMCP
    except ImportError:
        raise ImportError("FastMCP not found. Install: pip install 'mcp>=1.9.4,<2' OR pip install fastmcp")
from bs4 import BeautifulSoup

mcp = FastMCP("sovereign-web-search")

# --- Sovereign Helpers ---

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
]

def random_headers():
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate",
        "Referer": "https://www.google.com/",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }

def sovereign_headers():
    # For Wikimedia etc, include contact
    h = random_headers()
    h["User-Agent"] = "Sovereign-WebSearch/1.0 (MCP; sovereign, no-key; contact: sovereign@localhost) " + h["User-Agent"]
    return h

def clean_text(text: str, max_len: int = 8000) -> str:
    text = re.sub(r'\n\s*\n', '\n\n', text)
    text = re.sub(r' +', ' ', text)
    text = text.strip()
    if len(text) > max_len:
        return text[:max_len] + "\n...[truncated]"
    return text

def normalize_url(url: str) -> str:
    try:
        parsed = urllib.parse.urlparse(url)
        # strip tracking params
        q = urllib.parse.parse_qs(parsed.query)
        for k in list(q.keys()):
            if k.startswith("utm_") or k in ("utm_source","utm_medium","utm_campaign","fbclid","gclid","yclid","msclkid"):
                q.pop(k, None)
        new_query = urllib.parse.urlencode(q, doseq=True)
        return urllib.parse.urlunparse((parsed.scheme, parsed.netloc.lower(), parsed.path.rstrip("/"), parsed.params, new_query, ""))
    except:
        return url

def decode_bing_url(bing_url: str) -> str:
    """Bing wraps URLs as https://www.bing.com/ck/a?...&u=a1aHR0cHM6Ly..."""
    if "bing.com/ck/a" not in bing_url:
        return bing_url
    m = re.search(r"[?&]u=([^&]+)", bing_url)
    if not m:
        return bing_url
    b64 = m.group(1)
    # Try stripping leading version bytes like 'a1', 'a2', 'b1'
    for prefix_len in [2, 0, 4]:
        if prefix_len > len(b64):
            continue
        candidate = b64[prefix_len:]
        # add padding
        candidate += "=" * (-len(candidate) % 4)
        try:
            decoded = base64.b64decode(candidate).decode("utf-8", errors="ignore")
            if decoded.startswith("http"):
                return decoded
        except:
            continue
    # fallback: url decode
    try:
        return urllib.parse.unquote(b64)
    except:
        return bing_url

def decode_ddg_url(ddg_url: str) -> str:
    if "uddg=" in ddg_url:
        m = re.search(r"uddg=([^&]+)", ddg_url)
        if m:
            return urllib.parse.unquote(m.group(1))
    return ddg_url

# --- Sovereign Scrapers (NO API KEYS) ---

async def scrape_duckduckgo(query: str, count: int) -> list[dict]:
    """DuckDuckGo HTML - most reliable sovereign engine, no JS"""
    try:
        headers = random_headers()
        headers["Referer"] = "https://html.duckduckgo.com/"
        async with httpx.AsyncClient(timeout=15, follow_redirects=True, headers=headers) as client:
            # POST is more reliable for html.duckduckgo.com/html/
            data = {"q": query}
            resp = await client.post("https://html.duckduckgo.com/html/", data=data)
            if resp.status_code != 200 or "no results" in resp.text.lower() and len(resp.text) < 3000:
                # fallback GET
                resp = await client.get("https://html.duckduckgo.com/html/", params={"q": query})
            resp.raise_for_status()
            if "challenge" in resp.text.lower() and "confirm this search was made by a human" in resp.text.lower():
                return []  # bot challenge, but html endpoint rarely does this vs lite
            soup = BeautifulSoup(resp.text, "lxml")
            results = []
            for div in soup.select("div.result")[:count*4]:  # get extra then filter ads
                a = div.select_one("a.result__a")
                if not a:
                    continue
                href = a.get("href", "")
                url = decode_ddg_url(href)
                if not url.startswith("http"):
                    continue
                # Filter ads and trackers - sovereign clean
                if any(x in url for x in ["y.js?", "ad_domain", "aclick", "aclk", "bing.com/a", "duckduckgo.com/y.js"]):
                    continue
                # Also filter divs that are ads (contain ad badge)
                if div.select_one(".result__ad, .badge--ad"):
                    continue
                title = a.get_text(strip=True)
                if not title or len(title) < 3:
                    continue
                snippet_el = div.select_one(".result__snippet")
                snippet = snippet_el.get_text(strip=True) if snippet_el else ""
                # also try result__url for display url fallback
                if not snippet:
                    snippet = div.get_text(strip=True)[:300]
                results.append({"title": title, "url": url, "snippet": snippet, "engine": "duckduckgo"})
                if len(results) >= count:
                    break
            return results
    except Exception as e:
        print(f"[duckduckgo] error: {e}")
        return []

async def scrape_bing(query: str, count: int) -> list[dict]:
    """Bing - sovereign, server-rendered HTML, needs redirect decode"""
    try:
        headers = random_headers()
        headers["Referer"] = "https://www.bing.com/"
        async with httpx.AsyncClient(timeout=15, follow_redirects=True, headers=headers) as client:
            resp = await client.get("https://www.bing.com/search", params={"q": query, "count": str(count)})
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")
            results = []
            for li in soup.select("li.b_algo")[:count*2]:
                a = li.select_one("h2 a")
                if not a:
                    continue
                raw_url = a.get("href", "")
                url = decode_bing_url(raw_url)
                if not url.startswith("http"):
                    continue
                # filter bing internal
                if "bing.com" in url and "/ck/a" in url:
                    continue
                title = a.get_text(strip=True)
                p = li.select_one("div.b_caption p, p")
                snippet = p.get_text(strip=True) if p else ""
                if not snippet:
                    # fallback: get text from li without h2
                    snippet = li.get_text(strip=True)[:300]
                results.append({"title": title, "url": url, "snippet": snippet, "engine": "bing"})
                if len(results) >= count:
                    break
            return results
    except Exception as e:
        print(f"[bing] error: {e}")
        return []

async def scrape_brave(query: str, count: int) -> list[dict]:
    """Brave Search - independent index, sovereign. May 429 in cloud datacenters."""
    try:
        headers = random_headers()
        headers["Referer"] = "https://search.brave.com/"
        async with httpx.AsyncClient(timeout=12, follow_redirects=True, headers=headers) as client:
            resp = await client.get("https://search.brave.com/search", params={"q": query, "source": "web"})
            if resp.status_code == 429:
                # rate limited / captcha required
                return []
            resp.raise_for_status()
            text = resp.text
            if "captcha" in text.lower() or "This page needs JavaScript" in text:
                return []
            soup = BeautifulSoup(text, "lxml")
            results = []
            # Brave selectors as of 2026: div.snippet, or data-type web
            # Try multiple selectors
            candidates = soup.select("div.snippet") or soup.select("[data-type='web']") or soup.select("div.result")
            if not candidates:
                # fallback: look for anchors with description nearby
                candidates = soup.select("div#results > div")
            for div in candidates[:count*2]:
                # title
                a = div.select_one("a.snippet-title, a.result-header, h2 a, a[href^='http']")
                if not a:
                    continue
                url = a.get("href", "")
                if not url.startswith("http"):
                    continue
                if "brave.com" in url:
                    continue
                title = a.get_text(strip=True)
                if not title or len(title) < 3:
                    continue
                desc = div.select_one("div.snippet-description, p.snippet-description, div.description, p")
                snippet = desc.get_text(strip=True) if desc else ""
                results.append({"title": title, "url": url, "snippet": snippet, "engine": "brave"})
                if len(results) >= count:
                    break
            return results
    except Exception as e:
        print(f"[brave] error: {e}")
        return []

async def scrape_mojeek(query: str, count: int) -> list[dict]:
    """Mojeek - independent UK index, sovereign"""
    try:
        headers = random_headers()
        async with httpx.AsyncClient(timeout=12, follow_redirects=True, headers=headers) as client:
            resp = await client.get("https://www.mojeek.com/search", params={"q": query})
            if resp.status_code == 403 and "automated queries" in resp.text:
                return []
            resp.raise_for_status()
            if "403 - Forbidden" in resp.text:
                return []
            soup = BeautifulSoup(resp.text, "lxml")
            results = []
            # Mojeek: ul.results-standard li, or div.result
            for li in (soup.select("ul.results-standard li") or soup.select("li.result") or soup.select("div.result"))[:count*2]:
                a = li.select_one("a.ob, h2 a, a[href^='http']")
                if not a:
                    continue
                url = a.get("href", "")
                if not url.startswith("http"):
                    # mojeek may use relative /search? etc skip
                    continue
                title = a.get_text(strip=True)
                desc = li.select_one("p.s, p.description, p.aec")
                snippet = desc.get_text(strip=True) if desc else ""
                results.append({"title": title, "url": url, "snippet": snippet, "engine": "mojeek"})
                if len(results) >= count:
                    break
            return results
    except Exception as e:
        print(f"[mojeek] error: {e}")
        return []

async def scrape_yahoo(query: str, count: int) -> list[dict]:
    """Yahoo Search - fallback"""
    try:
        headers = random_headers()
        headers["Referer"] = "https://search.yahoo.com/"
        async with httpx.AsyncClient(timeout=12, follow_redirects=True, headers=headers) as client:
            resp = await client.get("https://search.yahoo.com/search", params={"p": query, "n": str(count)})
            if resp.status_code != 200:
                return []
            soup = BeautifulSoup(resp.text, "lxml")
            results = []
            # Yahoo: div.algo, or li with h3
            for div in (soup.select("div.algo") or soup.select("div.dd.algo") or soup.select("li div.compTitle"))[:count*2]:
                a = div.select_one("h3 a, a[href^='http']")
                if not a:
                    continue
                url = a.get("href", "")
                if not url.startswith("http"):
                    continue
                # yahoo wraps via r.search.yahoo.com? skip if not decoded
                if "r.search.yahoo.com" in url:
                    # try to extract actual url from RU param
                    m = re.search(r"RU=([^&]+)", url)
                    if m:
                        url = urllib.parse.unquote(m.group(1))
                title = a.get_text(strip=True)
                desc = div.select_one("div.compText, p, span")
                snippet = desc.get_text(strip=True) if desc else ""
                results.append({"title": title, "url": url, "snippet": snippet, "engine": "yahoo"})
                if len(results) >= count:
                    break
            return results
    except Exception as e:
        print(f"[yahoo] error: {e}")
        return []

async def scrape_google(query: str, count: int) -> list[dict]:
    """Google - best-effort sovereign scrape, often requires JS, may fail"""
    try:
        headers = random_headers()
        headers["Referer"] = "https://www.google.com/"
        # Google blocks easily, try with minimal params
        params = {"q": query, "num": str(count), "hl": "en", "gl": "us"}
        async with httpx.AsyncClient(timeout=12, follow_redirects=True, headers=headers) as client:
            resp = await client.get("https://www.google.com/search", params=params)
            if resp.status_code != 200:
                return []
            text = resp.text
            if "enablejs" in text.lower() or "Our systems have detected unusual traffic" in text:
                return []
            soup = BeautifulSoup(text, "lxml")
            results = []
            # Google 2026 structure: div.g, div[data-hveid], or div.MjjYud
            for div in (soup.select("div.g") or soup.select("div.MjjYud") or soup.select("div[data-hveid]"))[:count*2]:
                a = div.select_one("a[href^='http'] h3")
                # alternative: h3 inside a
                if not a:
                    h3 = div.select_one("h3")
                    if h3 and h3.parent and h3.parent.name == "a":
                        a = h3
                    else:
                        continue
                # find parent a
                link = a.parent if a.parent.name == "a" else div.select_one("a[href^='http']")
                if not link:
                    continue
                url = link.get("href", "")
                if not url.startswith("http"):
                    continue
                # filter google internal
                if "google.com" in url:
                    continue
                title = a.get_text(strip=True) if hasattr(a, "get_text") else link.get_text(strip=True)
                # snippet
                snippet_el = div.select_one("div.VwiC3b, span.aCOpRe, div.IsZvec")
                snippet = snippet_el.get_text(strip=True) if snippet_el else ""
                results.append({"title": title, "url": url, "snippet": snippet, "engine": "google"})
                if len(results) >= count:
                    break
            return results
    except Exception as e:
        print(f"[google] error: {e}")
        return []

async def scrape_wikipedia(query: str, count: int) -> list[dict]:
    """Wikipedia - sovereign open API, no key, no scraping, direct JSON"""
    try:
        # Wikimedia requires proper UA with contact; use sovereign_headers
        headers = sovereign_headers()
        headers["Accept"] = "application/json"
        # Try query search first (more robust than opensearch)
        async with httpx.AsyncClient(timeout=10, follow_redirects=True, headers=headers) as client:
            resp = await client.get("https://en.wikipedia.org/w/api.php", params={
                "action": "query",
                "list": "search",
                "srsearch": query,
                "srlimit": str(count),
                "format": "json",
                "utf8": "1",
                "origin": "*"
            })
            if resp.status_code == 403:
                # Fallback: try with Api-User-Agent header (Wikimedia specific)
                headers["Api-User-Agent"] = "Sovereign-WebSearch/1.0 (sovereign@mcp.local)"
                resp = await client.get("https://en.wikipedia.org/w/api.php", params={
                    "action": "query",
                    "list": "search",
                    "srsearch": query,
                    "srlimit": str(count),
                    "format": "json"
                }, headers=headers)
            resp.raise_for_status()
            try:
                data = resp.json()
            except:
                return []
            results = []
            for item in data.get("query", {}).get("search", [])[:count]:
                title = item.get("title", "")
                snippet_html = item.get("snippet", "")
                snippet = BeautifulSoup(snippet_html, "lxml").get_text(strip=True) if snippet_html else ""
                url = f"https://en.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}"
                results.append({"title": title + " - Wikipedia", "url": url, "snippet": snippet, "engine": "wikipedia"})
            return results
    except Exception as e:
        # Don't print 403 as error spam
        if "403" not in str(e):
            print(f"[wikipedia] error: {e}")
        return []

# Engine registry - sovereign, no keys
ENGINES = {
    "duckduckgo": {"name": "DuckDuckGo", "func": scrape_duckduckgo, "sovereign": True, "desc": "Privacy, no JS, most reliable"},
    "bing":       {"name": "Bing",       "func": scrape_bing,       "sovereign": True, "desc": "Microsoft, server-rendered, reliable"},
    "brave":      {"name": "Brave",      "func": scrape_brave,      "sovereign": True, "desc": "Independent index, privacy"},
    "mojeek":     {"name": "Mojeek",     "func": scrape_mojeek,     "sovereign": True, "desc": "Independent UK index"},
    "yahoo":      {"name": "Yahoo",      "func": scrape_yahoo,      "sovereign": True, "desc": "Fallback"},
    "google":     {"name": "Google",     "func": scrape_google,     "sovereign": True, "desc": "Best-effort, may block without JS"},
    "wikipedia":  {"name": "Wikipedia",  "func": scrape_wikipedia,  "sovereign": True, "desc": "Open API, no key, encyclopedic"},
}

# --- Sovereign Fetch (direct httpx, no external service) ---

async def sovereign_fetch(url: str, max_len: int = 10000) -> str:
    """Directly fetch URL and extract readable text, no external service"""
    try:
        headers = random_headers()
        async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers=headers) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            ctype = resp.headers.get("content-type", "")
            if "application/json" in ctype:
                try:
                    j = resp.json()
                    return clean_text(json.dumps(j, indent=2), max_len)
                except:
                    return clean_text(resp.text, max_len)
            soup = BeautifulSoup(resp.text, "lxml")
            for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript", "iframe"]):
                tag.decompose()
            # try readability: main/article
            main = soup.find("main") or soup.find("article") or soup.find("div", {"role": "main"}) or soup.body
            text = ""
            if main:
                # preserve headings
                for h in main.find_all(["h1","h2","h3"]):
                    h.insert_before("\n\n## ")
                    h.insert_after("\n")
                text = main.get_text(separator="\n", strip=True)
            else:
                text = soup.get_text(separator="\n", strip=True)
            text = re.sub(r"\n{3,}", "\n\n", text)
            title = soup.title.string.strip() if soup.title and soup.title.string else ""
            if title:
                text = f"# {title}\n\n{text}"
            return clean_text(text, max_len)
    except Exception as e:
        return f"Failed to fetch {url}: {e}"

# --- Sovereign Meta-Search ---

async def sovereign_search(query: str, count: int, engines: list[str]) -> tuple[list[dict], dict]:
    """Query multiple sovereign engines in parallel, deduplicate by URL"""
    tasks = []
    for eng in engines:
        if eng in ENGINES:
            tasks.append(ENGINES[eng]["func"](query, count))
        else:
            tasks.append(asyncio.sleep(0, result=[]))
    results_per_engine = await asyncio.gather(*tasks, return_exceptions=True)
    # collect stats
    stats = {}
    all_results = []
    seen = set()
    for eng, res in zip(engines, results_per_engine):
        if isinstance(res, Exception):
            stats[eng] = f"error: {res}"
            continue
        if not isinstance(res, list):
            stats[eng] = "invalid result"
            continue
        stats[eng] = f"{len(res)} results"
        for r in res:
            norm = normalize_url(r.get("url",""))
            if not norm or norm in seen:
                continue
            seen.add(norm)
            all_results.append(r)
            if len(all_results) >= count:
                break
        if len(all_results) >= count:
            break
    # if not enough, keep adding round-robin from remaining
    if len(all_results) < count:
        for res in results_per_engine:
            if isinstance(res, list):
                for r in res:
                    norm = normalize_url(r.get("url",""))
                    if norm not in seen:
                        seen.add(norm)
                        all_results.append(r)
                    if len(all_results) >= count:
                        break
            if len(all_results) >= count:
                break
    return all_results[:count], stats

# --- MCP Tools (direct MCP stdio) ---

@mcp.tool()
async def search_web(
    query: str,
    count: int = 8,
    engines: str = "auto"
) -> str:
    """
    Sovereign web search - directly scrapes search engines, no API keys, no external company.
    
    Args:
        query: Search query - be specific (e.g. "sovereign MCP server python 2026")
        count: Number of results 1-20 (default 8)
        engines: "auto" (duckduckgo+bing+wikipedia, most reliable),
                 "all" (tries all 7 engines in parallel),
                 or comma-separated like "duckduckgo,bing,brave,wikipedia" or single "duckduckgo"
    """
    query = query.strip()
    if not query:
        return "Error: query cannot be empty"
    count = max(1, min(20, count))
    engines = engines.strip().lower()
    if engines == "auto":
        engine_list = ["duckduckgo", "bing", "wikipedia"]
    elif engines == "all":
        engine_list = ["duckduckgo", "bing", "brave", "mojeek", "yahoo", "google", "wikipedia"]
    else:
        # parse comma list
        engine_list = [e.strip() for e in engines.split(",") if e.strip() in ENGINES]
        if not engine_list:
            return f"Unknown engines '{engines}'. Available: {', '.join(ENGINES.keys())} + auto/all"

    results, stats = await sovereign_search(query, count, engine_list)

    if not results:
        stats_str = ", ".join([f"{k}: {v}" for k,v in stats.items()])
        return f"""# No Results

**Query:** `{query}`
**Engines:** `{', '.join(engine_list)}`
**Stats:** {stats_str}

> Tip: try different query or `engines=\"all\"` for broader coverage.
"""

    # Clear markdown: header + metadata + table + detailed sections
    def esc_md(s: str) -> str:
        return s.replace("|", "\\|").replace("\n", " ").strip()

    out = f"# Sovereign Search Results\n\n"
    out += f"**Query:** `{esc_md(query)}` | **Engines:** `{', '.join(engine_list)}` | **Found:** `{len(results)}` | **Sovereign:** `no API key, direct scrape`\n\n"
    out += f"**Engine Stats:** {', '.join([f'`{k}`: {v}' for k,v in stats.items()])}\n\n"
    out += f"## Summary Table\n\n"
    out += f"| # | Title | Engine | URL |\n"
    out += f"|---|-------|--------|-----|\n"
    for i, r in enumerate(results, 1):
        title = esc_md(clean_text(r.get("title","Untitled") or "Untitled", 80))
        url = r.get("url","")
        eng = r.get("engine","unknown")
        # truncate URL for table
        url_disp = url if len(url) < 60 else url[:57] + "..."
        out += f"| {i} | {title} | `{eng}` | [{url_disp}]({url}) |\n"
    out += f"\n## Detailed Results\n\n"
    for i, r in enumerate(results, 1):
        title = clean_text(r.get("title","Untitled") or "Untitled", 200).strip()
        url = r.get("url","")
        snippet = clean_text(r.get("snippet",""), 500)
        eng = r.get("engine","unknown")
        out += f"### {i}. {title}\n\n"
        out += f"- **Engine:** `{eng}`\n"
        out += f"- **URL:** [{url}]({url})\n"
        if snippet:
            out += f"- **Snippet:** {snippet}\n"
        out += f"\n---\n\n"
    out += f"> **Sovereign:** directly scraped via `httpx` + `BeautifulSoup`, no external API key. Use `fetch_page(url)` for full markdown content.\n"
    out += f"> **MCP:** `search_web` via `stdio JSON-RPC 2.0` (`FastMCP`)\n"
    # Also include clear structured data block for programmatic use (still markdown)
    out += f"\n<details>\n<summary>📦 Structured Data (JSON)</summary>\n\n```json\n"
    out += json.dumps([{"rank": i, "title": r.get("title"), "url": r.get("url"), "engine": r.get("engine"), "snippet": clean_text(r.get("snippet",""), 300)} for i, r in enumerate(results, 1)], indent=2, ensure_ascii=False)
    out += f"\n```\n</details>\n"
    return out

@mcp.tool()
async def fetch_page(
    url: str,
    max_length: int = 10000,
    extract_mode: str = "text"
) -> str:
    """
    Sovereign fetch - directly fetch URL and extract readable markdown, no external service.
    Returns clear markdown with metadata + content.
    
    Args:
        url: Full URL (http:// or https://)
        max_length: 1000-30000 (default 10000)
        extract_mode: "text" (clean), "markdown", or "html" (raw)
    """
    max_length = max(1000, min(30000, max_length))
    if not url.startswith(("http://","https://")):
        return f"# Error\n\n**Message:** URL must start with `http://` or `https://`\n\n**Received:** `{url}`\n"
    if extract_mode == "html":
        try:
            headers = random_headers()
            async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers=headers) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                return f"# Fetched: {url}\n\n**Mode:** `html` | **Length:** `{len(resp.text)}` | **Truncated:** `{max_length}`\n\n```html\n{resp.text[:max_length]}\n```\n"
        except Exception as e:
            return f"# Fetch Failed\n\n**URL:** `{url}`\n\n**Error:** `{e}`\n"
    content = await sovereign_fetch(url, max_length)
    if content.startswith("Failed to fetch"):
        return f"# Fetch Failed\n\n**URL:** `{url}`\n\n**Error:** {content}\n"
    # Clear markdown with metadata header
    out = f"# Fetched Content\n\n"
    out += f"**Source:** [{url}]({url}) | **Mode:** `{extract_mode}` | **Length:** `{len(content)}` chars\n\n"
    out += f"---\n\n"
    out += content
    out += f"\n\n---\n\n> **Sovereign Fetch:** direct `httpx` + `BeautifulSoup` readability, no external API. **MCP:** `fetch_page` via `stdio`\n"
    return out

@mcp.tool()
async def search_and_fetch(
    query: str,
    count: int = 5,
    fetch_top: int = 2,
    engines: str = "auto"
) -> str:
    """
    Sovereign search + fetch - search then directly fetch top results for deeper context.
    
    Args:
        query: Search query
        count: Number of search results 1-10 (default 5)
        fetch_top: How many top URLs to fetch 0-3 (default 2)
        engines: same as search_web: auto/all or comma list
    """
    count = max(1, min(10, count))
    fetch_top = max(0, min(3, fetch_top))
    search_result = await search_web(query, count, engines)
    if fetch_top == 0 or "No results" in search_result:
        return search_result
    # Re-run sovereign_search to get structured results for fetching
    engines_clean = engines.strip().lower()
    if engines_clean == "auto":
        engine_list = ["duckduckgo","bing","wikipedia"]
    elif engines_clean == "all":
        engine_list = ["duckduckgo","bing","brave","mojeek","yahoo","google","wikipedia"]
    else:
        engine_list = [e.strip() for e in engines_clean.split(",") if e.strip() in ENGINES]
        if not engine_list:
            engine_list = ["duckduckgo","bing","wikipedia"]
    results, _ = await sovereign_search(query, count, engine_list)
    if not results:
        return search_result
    out = search_result + "\n\n---\n\n# 📄 Sovereign Fetched Content\n\n"
    out += f"**Query:** `{query}` | **Fetched:** `{min(fetch_top, len(results))}/{len(results)}` top results | **Method:** `direct httpx` (sovereign)\n\n"
    for idx, r in enumerate(results[:fetch_top], 1):
        url = r.get("url")
        if not url:
            continue
        out += f"## {idx}. {r.get('title')} `[{r.get('engine')}]`\n\n"
        out += f"**URL:** [{url}]({url})\n\n"
        content = await sovereign_fetch(url, 5000)
        # content already has its own header, but we wrap it clearly
        out += f"<details>\n<summary>📖 Full Content ({len(content)} chars)</summary>\n\n"
        out += content
        out += f"\n</details>\n\n---\n\n"
    return out

@mcp.tool()
async def list_engines() -> str:
    """
    List all sovereign search engines supported (no API keys).
    """
    out = "# Sovereign Search Engines (No API Key, Direct Scraping)\n\n"
    out += "All engines are scraped directly via HTTP + HTML parsing. No external company, no key, no monopoly.\n\n"
    out += "| Engine | Status | Description | Sovereign |\n"
    out += "|--------|--------|-------------|-----------|\n"
    for key, info in ENGINES.items():
        out += f"| `{key}` | ✅ active | {info['desc']} | direct scrape |\n"
    out += "\n**Modes:**\n"
    out += "- `engines=\"auto\"` → `duckduckgo,bing,wikipedia` (most reliable, recommended)\n"
    out += "- `engines=\"all\"` → tries all 7 in parallel (best coverage, slower)\n"
    out += "- `engines=\"duckduckgo,bing\"` → custom comma list\n"
    out += "\n**Fetch:** `fetch_page` directly fetches any URL via httpx, no external service.\n"
    out += "**MCP:** This server communicates directly via MCP stdio JSON-RPC 2.0 (FastMCP).\n"
    return out

def main():
    mcp.run()

if __name__ == "__main__":
    main()
