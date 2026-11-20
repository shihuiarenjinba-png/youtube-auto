"""URL-grounded advertising research, adapted from auto-blogger.

The fetcher validates every redirect and accepts public HTTPS destinations only.
Generation is deterministic and uses extracted evidence verbatim; absent facts
remain absent rather than being invented.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import socket
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup


SPACE_RE = re.compile(r"\s+")
PRICE_RE = re.compile(
    r"(?:月額|年額|料金|価格|price|pricing)?\s*(?:[￥¥$]\s*)?"
    r"[0-9０-９][0-9０-９,，.．]*\s*(?:円|万円|税込|税別|/月|/年|USD|ドル|per month)",
    re.IGNORECASE,
)
CAMPAIGN_WORDS = ("キャンペーン", "割引", "特典", "無料期間", "discount", "offer", "free trial")
RESTRICTION_WORDS = ("注意", "対象外", "条件", "返金", "自動更新", "terms", "restriction", "eligible")
BENEFIT_WORDS = ("できる", "向上", "削減", "簡単", "効率", "benefit", "save", "improve", "easier", "faster")
CTA_WORDS = ("詳しく", "申し込", "始める", "試す", "購入", "learn more", "get started", "try", "buy", "sign up")


class RagHold(RuntimeError):
    pass


def clean(value: str, limit: int = 500) -> str:
    return SPACE_RE.sub(" ", unicodedata.normalize("NFKC", value or "")).strip()[:limit]


def unique(values: list[str], limit: int) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = clean(raw)
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            result.append(value)
        if len(result) >= limit:
            break
    return result


def validate_public_https(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme != "https":
        raise RagHold("HOLD_SOURCE_URL_NOT_HTTPS")
    if not parsed.hostname or parsed.username or parsed.password:
        raise RagHold("HOLD_SOURCE_URL_INVALID_HOST")
    hostname = parsed.hostname.rstrip(".")
    if hostname.lower() == "localhost" or hostname.lower().endswith(".localhost"):
        raise RagHold("HOLD_SOURCE_URL_LOCALHOST")
    try:
        addresses = socket.getaddrinfo(hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise RagHold("HOLD_SOURCE_URL_DNS_FAILED") from exc
    if not addresses:
        raise RagHold("HOLD_SOURCE_URL_DNS_EMPTY")
    for address in addresses:
        if not ipaddress.ip_address(address[4][0]).is_global:
            raise RagHold("HOLD_SOURCE_URL_NON_PUBLIC_IP")


@dataclass(slots=True)
class GroundedSource:
    campaign_id: str
    source_url: str
    canonical_url: str
    generated_from_source_hash: str
    fetched_at: str
    page_title: str = ""
    meta_description: str = ""
    main_visible_body: str = ""
    product_or_service_name: str = ""
    features: list[str] = field(default_factory=list)
    benefits: list[str] = field(default_factory=list)
    prices: list[str] = field(default_factory=list)
    campaigns: list[str] = field(default_factory=list)
    restrictions: list[str] = field(default_factory=list)
    ctas: list[dict[str, str]] = field(default_factory=list)
    evidence_snippets: list[str] = field(default_factory=list)


class PublicHttpsFetcher:
    def __init__(self, *, timeout: int = 20, max_bytes: int = 4 * 1024 * 1024, max_redirects: int = 5):
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.max_redirects = max_redirects
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "youtube-auto-advertising-rag/1.0",
            "Accept": "text/html,application/xhtml+xml;q=0.9",
        })

    def fetch(self, url: str) -> tuple[str, bytes, str]:
        current = url
        for redirect_count in range(self.max_redirects + 1):
            validate_public_https(current)
            try:
                response = self.session.get(current, allow_redirects=False, stream=True, timeout=self.timeout)
            except requests.RequestException as exc:
                raise RagHold("HOLD_SOURCE_FETCH_FAILED") from exc
            try:
                if response.is_redirect or response.is_permanent_redirect:
                    location = response.headers.get("Location", "")
                    if not location or redirect_count >= self.max_redirects:
                        raise RagHold("HOLD_SOURCE_REDIRECT_INVALID")
                    current = urljoin(current, location)
                    continue
                if response.status_code >= 400:
                    raise RagHold(f"HOLD_SOURCE_HTTP_{response.status_code}")
                content_type = response.headers.get("Content-Type", "").lower()
                if not content_type.startswith(("text/html", "application/xhtml+xml")):
                    raise RagHold("HOLD_SOURCE_NOT_HTML")
                declared = response.headers.get("Content-Length")
                if declared and declared.isdigit() and int(declared) > self.max_bytes:
                    raise RagHold("HOLD_SOURCE_TOO_LARGE")
                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_content(64 * 1024):
                    total += len(chunk)
                    if total > self.max_bytes:
                        raise RagHold("HOLD_SOURCE_TOO_LARGE")
                    chunks.append(chunk)
                body = b"".join(chunks)
                try:
                    apparent_encoding = requests.models.chardet.detect(body).get("encoding")
                except (AttributeError, TypeError):
                    apparent_encoding = None
                html = self._decode_html(
                    body,
                    content_type,
                    apparent_encoding,
                )
                return current, body, html
            finally:
                response.close()
        raise RagHold("HOLD_SOURCE_REDIRECT_LIMIT")

    @staticmethod
    def _decode_html(body: bytes, content_type: str, apparent_encoding: str | None) -> str:
        if body.startswith(b"\xef\xbb\xbf"):
            return body.decode("utf-8-sig", errors="replace")
        header_match = re.search(r"charset\s*=\s*['\"]?([^;\s'\"]+)", content_type)
        meta_match = re.search(
            br"<meta[^>]+charset\s*=\s*['\"]?\s*([A-Za-z0-9._-]+)",
            body[:16384],
            re.IGNORECASE,
        )
        encoding = (
            (header_match.group(1) if header_match else "")
            or (meta_match.group(1).decode("ascii") if meta_match else "")
            or apparent_encoding
            or "utf-8"
        )
        return body.decode(encoding, errors="replace")


class GroundedExtractor:
    def extract(self, *, campaign_id: str, requested_url: str, final_url: str, body: bytes, html: str) -> GroundedSource:
        soup = BeautifulSoup(html, "html.parser")
        canonical_element = soup.select_one('link[rel="canonical"][href]')
        canonical = urljoin(final_url, str(canonical_element.get("href"))) if canonical_element else final_url
        validate_public_https(canonical)
        title = self._meta(soup, 'meta[property="og:title"]') or clean(soup.title.get_text(" ", strip=True) if soup.title else "")
        description = self._meta(soup, 'meta[name="description"]') or self._meta(soup, 'meta[property="og:description"]')
        product_name, json_features, json_prices = self._jsonld(soup)
        for element in soup(["script", "style", "noscript", "svg", "nav", "footer", "header"]):
            element.decompose()
        main = soup.select_one("main, article, [role='main']") or soup.body
        visible = clean(main.get_text(" ", strip=True) if main else "", 6000)
        blocks = unique([
            element.get_text(" ", strip=True)
            for element in soup.select("main p, main li, article p, article li, [role='main'] p, body p, body li")
            if 8 <= len(element.get_text(" ", strip=True)) <= 600
        ], 200)
        headings = unique([e.get_text(" ", strip=True) for e in soup.select("h1,h2,h3")], 20)
        features = unique(json_features + [x for x in blocks + headings[1:] if 12 <= len(x) <= 220], 10)
        benefits = unique([x for x in blocks if any(word in x.casefold() for word in BENEFIT_WORDS)], 8)
        prices = unique(json_prices + [x for x in blocks if PRICE_RE.search(x)], 6)
        campaigns = unique([x for x in blocks if any(word in x.casefold() for word in CAMPAIGN_WORDS)], 6)
        restrictions = unique([x for x in blocks if any(word in x.casefold() for word in RESTRICTION_WORDS)], 6)
        ctas: list[dict[str, str]] = []
        for link in soup.select("a[href], button"):
            text = clean(link.get_text(" ", strip=True), 120)
            if text and any(word in text.casefold() for word in CTA_WORDS):
                href = urljoin(final_url, str(link.get("href") or "")) if link.name == "a" else ""
                href_parts = urlsplit(href)
                final_parts = urlsplit(final_url)
                # CTA navigation is retained only when it stays on the already
                # validated HTTPS source host. External or non-HTTPS targets are
                # omitted instead of being guessed or followed.
                if not href or (
                    href_parts.scheme == "https"
                    and href_parts.hostname == final_parts.hostname
                ):
                    ctas.append({"text": text, "url": href})
        evidence = unique([title, description, *headings, *benefits, *features, *prices, *campaigns, *restrictions], 20)
        result = GroundedSource(
            campaign_id=campaign_id,
            source_url=requested_url,
            canonical_url=canonical,
            generated_from_source_hash=hashlib.sha256(body).hexdigest(),
            fetched_at=datetime.now(timezone.utc).isoformat(),
            page_title=title,
            meta_description=description,
            main_visible_body=visible,
            product_or_service_name=product_name or (headings[0] if headings else title),
            features=features,
            benefits=benefits,
            prices=prices,
            campaigns=campaigns,
            restrictions=restrictions,
            ctas=ctas[:6],
            evidence_snippets=evidence,
        )
        if not result.product_or_service_name or not result.main_visible_body or len(result.evidence_snippets) < 3:
            raise RagHold("HOLD_INSUFFICIENT_SOURCE_EVIDENCE")
        return result

    @staticmethod
    def _meta(soup: BeautifulSoup, selector: str) -> str:
        element = soup.select_one(selector)
        return clean(str(element.get("content") or "")) if element else ""

    @staticmethod
    def _jsonld(soup: BeautifulSoup) -> tuple[str, list[str], list[str]]:
        name = ""
        features: list[str] = []
        prices: list[str] = []

        def walk(value: object):
            if isinstance(value, dict):
                yield value
                for child in value.values():
                    yield from walk(child)
            elif isinstance(value, list):
                for child in value:
                    yield from walk(child)

        for script in soup.select('script[type="application/ld+json"]'):
            try:
                payload = json.loads(script.string or "")
            except (json.JSONDecodeError, TypeError):
                continue
            for item in walk(payload):
                types = item.get("@type", [])
                types = types if isinstance(types, list) else [types]
                if not set(types) & {"Product", "Service", "SoftwareApplication", "Offer"}:
                    continue
                if not name and isinstance(item.get("name"), str):
                    name = clean(item["name"])
                value = item.get("featureList")
                if isinstance(value, str):
                    features.append(value)
                elif isinstance(value, list):
                    features.extend(str(x) for x in value)
                if item.get("price") is not None:
                    prices.append(clean(f"{item.get('price')} {item.get('priceCurrency', '')}"))
        return name, features, prices


def generate_grounded_content(source: GroundedSource, *, market: str) -> dict:
    key_points = unique([*source.benefits, *source.features], 5)
    if len(key_points) < 2:
        raise RagHold("HOLD_INSUFFICIENT_SOURCE_EVIDENCE")
    summary = source.meta_description or source.evidence_snippets[1]
    cta = source.ctas[0] if source.ctas else {"text": "", "url": source.canonical_url}
    script_lines = [source.product_or_service_name, summary, *key_points[:3]]
    hashtags = ["#PR", "#広告", "#商品紹介"] if market == "jp" else ["#ad", "#product", "#review"]
    return {
        "campaign_id": source.campaign_id,
        "market": market.upper(),
        "source_url": source.source_url,
        "canonical_url": source.canonical_url,
        "generated_from_source_hash": source.generated_from_source_hash,
        "hook": source.page_title or source.product_or_service_name,
        "summary": summary,
        "value_proposition": key_points[0],
        "key_points": key_points,
        "cta": cta,
        "video_script": script_lines,
        "caption": "\n".join([summary, *key_points[:3], source.canonical_url]),
        "hashtags": hashtags,
        "grounding_status": "PASS",
        "evidence_snippets": source.evidence_snippets,
    }


def source_as_dict(source: GroundedSource) -> dict:
    return asdict(source)
