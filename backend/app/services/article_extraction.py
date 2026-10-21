"""기사 URL 보안 검사와 본문 추출/정규화를 담당합니다."""
from __future__ import annotations

import hashlib
import json
import re
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup, NavigableString, Tag

def valid_remote_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in ("https", "http") or not parsed.netloc:
        return False
    # 개인 실행용 앱이지만 로컬/사설 네트워크 URL 접근을 방지합니다.
    host = (parsed.hostname or "").lower()
    if host in ("localhost",) or host.endswith(".local"):
        return False
    import ipaddress
    try:
        ip = ipaddress.ip_address(host)
        if not ip.is_global:
            return False
    except ValueError:
        pass
    return True

ARTICLE_BODY_SELECTORS = [
    '#article-view-content-div',
    '#articleBody', '#article_body', '#article-body',
    '.news-article-body', '.story-body', '.entry-content', '.post-content',
    '.article-cont', '[itemprop="articleBody"] article', '[itemprop="articleBody"]',
    '.article-view-content', '.article_view_content', '.article-body',
    '.article_body', '.news-view-content', '.article-content', '.article_view', 'article'
]
ARTICLE_IMAGE_CLASS_MARKERS = ("img", "image", "fig", "figure", "caption", "photo")
ARTICLE_SUBTITLE_MARKER_PATTERN = re.compile(
    r"\bsub\s*title\b|\bsub\s*tit\b|\bsubheadline\b|\bsub\s*head(?:line)?\b|"
    r"\bdeck\b|\bdek\b|\bstrapline\b|\bstandfirst\b|"
    r"\b(?:article|news|headline)\s+summary\b|\b(?:summary|summury)\b",
    re.IGNORECASE,
)


def _is_image_caption_node(node) -> bool:
    """Match image-related class names without inspecting the element's prose."""
    if node.name == "figcaption":
        return True

    class_values = node.get("class", [])
    if isinstance(class_values, str):
        class_values = [class_values]
    class_name = " ".join(class_values)
    # Support hyphen/underscore-separated and camelCase class names, such as
    # image-caption, photoDesc, and articleFigure.
    token_source = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", class_name)
    class_tokens = re.findall(r"[a-z0-9]+", token_source.lower())
    has_image_marker = any(
        token.startswith(ARTICLE_IMAGE_CLASS_MARKERS)
        or token.endswith(ARTICLE_IMAGE_CLASS_MARKERS)
        for token in class_tokens
    )
    if not has_image_marker:
        return False

    # A generic image class may be on a wrapper around real article prose.
    if node.name != "p" and node.find("p") is not None:
        return False
    return True


ARTICLE_NOISE_SELECTORS = [
    'script', 'style', 'noscript', 'iframe', 'svg', 'form', 'button',
    'input', 'textarea', 'select', 'nav', 'header', 'footer', 'aside',
    '[id*="comment"]', '[class*="comment"]',
    '[id*="reply"]', '[class*="reply"]',
    '.article-tools', '.article-toolbar', '.article-footer', '.article-info',
    '.related-news', '.article-related', '.recommend', '.recommendation',
    '.recommended', '.latest-news', '.popular-news', '.news-list', '.article-list',
    '.tag-list', '.keyword-list', '.byline', '.reporter', '.share', '.sns',
    '.sidebar', '.widget', '.advertisement', '.ad-container',
    '.box-listNews', '.adBox', '.infoLine', '.updata-time',
    '[class*="related"]', '[id*="related"]', '[class*="recommend"]',
    '[id*="recommend"]', '[class*="advert"]', '[id*="advert"]',
    '[aria-label*="관련 기사"]'
]

# Some publishers place the tag, reporter, and recommendation blocks as plain
# text inside the article body container. Those blocks cannot be removed with
# DOM selectors, so trim them by their standalone heading labels as well.
ARTICLE_TAIL_HEADINGS = {
    "관련태그",
    "태그",
    "기자채널",
    "다른기사",
    "추천기사",
}
ARTICLE_TAIL_PATTERNS = [
    re.compile(r"저작권자|저작권\s*[:：=]|무단\s*전재|재배포\s*금지|\bcopyright\b|©|ⓒ", re.IGNORECASE),
    re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b"),
    re.compile(r"^◎\s*공감언론\s*뉴시스\b"),
]
ARTICLE_INLINE_CREDIT_PATTERNS = [
    re.compile(r"(?:^|[\s·|—-])(?:사진|이미지)\s*(?:(?:출처|제공|저작권)\s*)?[:：=]\s*", re.IGNORECASE),
    re.compile(r"(?:^|\s)(?:photo|image)\s+(?:(?:credit|source|by)\b|courtesy\s+of)\s*[:：=]?\s*", re.IGNORECASE),
]
ARTICLE_IMAGE_CREDIT_PATTERNS = [
    re.compile(r"^(?:사진|이미지)\s*(?:(?:출처|제공|저작권)\s*)?[:：=]\s*.+$", re.IGNORECASE),
    re.compile(r"^(?:사진|이미지)\s*(?:출처|제공|저작권)\s*[:：=]?\s*.*$", re.IGNORECASE),
    re.compile(r"^(?:자료\s*사진|사진\s*자료)\s*[:：=]?\s*.*$", re.IGNORECASE),
    re.compile(r"^(?:photo|image)\s*(?:(?:credit|source|by|courtesy\s+of)\s*)?[:：=]\s*.+$", re.IGNORECASE),
    re.compile(r"^(?:©|ⓒ|copyright(?:\s*©)?)\s*.+$", re.IGNORECASE),
]


def _clean_article_lines(raw_lines) -> str:
    lines = []
    for raw_line in raw_lines:
        line = re.sub(r"\s+", " ", str(raw_line)).strip()
        if not line:
            continue
        if any(pattern.match(line) for pattern in ARTICLE_IMAGE_CREDIT_PATTERNS):
            continue
        if not lines or line != lines[-1]:
            lines.append(line)
    return "\n".join(_trim_article_tail(lines))


def _trim_article_tail(lines: list[str]) -> list[str]:
    """Remove publisher metadata appended after the article's final paragraph."""
    for index, line in enumerate(lines):
        heading = re.sub(r"[\s:：#]+", "", line).lower()
        if heading in ARTICLE_TAIL_HEADINGS:
            return lines[:index]
        match = None
        for pattern in ARTICLE_TAIL_PATTERNS + ARTICLE_INLINE_CREDIT_PATTERNS:
            match = pattern.search(line)
            if match:
                break
        if match:
            # Preserve an article sentence if a publisher appended the copyright
            # notice to the same text line.
            article_text = line[:match.start()].rstrip(" ·|—-:")
            return lines[:index] + ([article_text] if article_text else [])
    return lines

def _clean_article_node(node) -> str:
    fragment=BeautifulSoup(str(node),'html.parser')
    for selector in ARTICLE_NOISE_SELECTORS:
        for unwanted in fragment.select(selector):
            unwanted.decompose()
    # Remove only nodes explicitly marked as image captions/descriptions. Do not
    # drop ordinary article paragraphs based on their wording or relevance.
    for caption in fragment.find_all(_is_image_caption_node):
        if caption.parent is not None:
            caption.decompose()
    return _clean_article_lines(fragment.get_text('\n', strip=True).splitlines())

def _jsonld_article_body(value):
    if isinstance(value,dict):
        body=value.get('articleBody') or value.get('articlebody')
        if isinstance(body,str) and len(body.strip())>=300:
            return body.strip()
        for nested in value.values():
            found=_jsonld_article_body(nested)
            if found:
                return found
    elif isinstance(value,list):
        for nested in value:
            found=_jsonld_article_body(nested)
            if found:
                return found
    return ''

def extract_article_text(soup):
    # 기사 본문을 감싸는 요소만 살펴보고 댓글·버튼·페이지 메뉴는 제외합니다.
    seen=set()
    for selector in ARTICLE_BODY_SELECTORS:
        for node in soup.select(selector):
            text=_clean_article_node(node)
            if len(text)>=300 and text not in seen:
                return text,'article_selector'
            seen.add(text)
    # 일부 사이트는 본문을 JSON-LD 메타데이터에만 넣습니다.
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            body=_jsonld_article_body(json.loads(script.string or script.get_text()))
            if body:
                return _clean_article_node(BeautifulSoup(body,'html.parser')),'json_ld'
        except (TypeError,ValueError,json.JSONDecodeError):
            continue
    raise ValueError('페이지에서 기사 본문 영역을 찾지 못했습니다. 기사 본문을 직접 붙여넣어 주세요.')

def _page_title(soup):
    for selector in ['meta[property="og:title"]','meta[name="twitter:title"]']:
        node=soup.select_one(selector)
        if node and node.get('content'):
            return node['content'].strip()
    node=soup.find('h1') or soup.find('title')
    return node.get_text(' ',strip=True) if node else ''


def _has_subtitle_marker(node) -> bool:
    values = [node.get("id", ""), node.get("itemprop", "")]
    classes = node.get("class", [])
    if isinstance(classes, str):
        classes = [classes]
    values.extend(classes)
    tokenized = []
    for value in values:
        spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(value))
        tokenized.extend(re.findall(r"[a-z0-9]+", spaced.lower()))
    return bool(ARTICLE_SUBTITLE_MARKER_PATTERN.search(" ".join(tokenized)))


def _is_byline_node(node) -> bool:
    names = [node.get("id", "")]
    classes = node.get("class", [])
    if isinstance(classes, str):
        classes = [classes]
    names.extend(classes)
    tokens = " ".join(str(value).lower() for value in names)
    if re.search(r"byline|reporter|author|writer|journalist|dateline", tokens):
        return True
    text = node.get_text(" ", strip=True)
    return bool(re.search(
        r"(?:^|\s)[가-힣A-Za-z]{2,12}\s*기자(?:\s|$)|(?:^|\s)기자\s*[:：]|"
        r"입력\s*[:：]|수정\s*[:：]|발행\s*[:：]",
        text,
    ))


def _subtitle_text(node, title: str) -> str:
    if not node or _is_image_caption_node(node) or node.find_parent(["figure", "figcaption"]):
        return ""
    fragment = BeautifulSoup(str(node), "html.parser")
    for caption in fragment.find_all(_is_image_caption_node):
        if caption.parent is not None:
            caption.decompose()
    text = re.sub(r"\s+", " ", fragment.get_text(" ", strip=True)).strip()
    if len(text) < 8 or len(text) > 500:
        return ""
    if re.sub(r"\s+", "", text).casefold() == re.sub(r"\s+", "", title).casefold():
        return ""
    return text


def _page_subtitle_nodes(soup, title: str):
    title_node = soup.find("h1")
    ordered_nodes = soup.find_all(True)
    positions = {id(node): index for index, node in enumerate(ordered_nodes)}
    title_position = positions.get(id(title_node), -1) if title_node else -1
    body_node = None
    for selector in ARTICLE_BODY_SELECTORS:
        body_node = next((
            node for node in soup.select(selector)
            if len(_clean_article_node(node)) >= 300
        ), None)
        if body_node is not None:
            break

    def appears_before_body(node) -> bool:
        if body_node is None:
            return True
        node_position = positions.get(id(node), -1)
        body_position = positions.get(id(body_node), -1)
        if node is body_node or body_node in node.parents:
            first_paragraph = body_node.find("p")
            return first_paragraph is None or node_position <= positions.get(id(first_paragraph), body_position)
        return node_position < body_position

    candidates = []

    def add_candidate(node) -> None:
        if node is None or any(parent in candidates for parent in node.parents):
            return
        text = _subtitle_text(node, title)
        if not text:
            return
        # Prefer a surrounding subtitle block over one of its nested headings,
        # so the same deck is not stored twice.
        nested = [candidate for candidate in candidates if candidate in node.descendants]
        for candidate in nested:
            candidates.remove(candidate)
        candidates.append(node)

    for node in ordered_nodes:
        if not _has_subtitle_marker(node) or _is_image_caption_node(node):
            continue
        if node.name in {"nav", "aside", "footer", "script", "style"}:
            continue
        if title_node and positions.get(id(node), -1) <= title_position:
            continue
        if not appears_before_body(node):
            continue
        if node.select_one(", ".join(ARTICLE_BODY_SELECTORS)) is not None:
            continue
        add_candidate(node)

    # An unmarked h2 directly beside the headline is a common publisher deck.
    # Only inspect the headline's siblings before body text begins; never promote
    # the first paragraph, which may be the article's real lead.
    if title_node:
        for sibling in title_node.next_siblings:
            if isinstance(sibling, NavigableString):
                continue
            if not isinstance(sibling, Tag):
                continue
            if _is_image_caption_node(sibling):
                continue
            if _is_byline_node(sibling):
                continue
            heading_candidate = sibling if sibling.name in {"h2", "h3", "h4"} else sibling.find(["h2", "h3", "h4"])
            if heading_candidate and appears_before_body(heading_candidate):
                add_candidate(heading_candidate)
                continue
            if sibling.select_one(", ".join(ARTICLE_BODY_SELECTORS)) is not None:
                break
            if sibling.name in {"p", "article"}:
                break
            if sibling.get_text(" ", strip=True):
                break

    # Some publishers put deck headings at the top of the article-body element.
    # Only headings before the first paragraph qualify. The first paragraph itself
    # remains the article lead and is never promoted to subtitle here.
    if body_node is not None:
        first_paragraph = body_node.find("p")
        first_paragraph_position = positions.get(id(first_paragraph), len(ordered_nodes))
        for heading in body_node.find_all(["h2", "h3", "h4"]):
            if positions.get(id(heading), len(ordered_nodes)) >= first_paragraph_position:
                break
            if not _is_image_caption_node(heading):
                add_candidate(heading)

    return sorted(candidates, key=lambda node: positions.get(id(node), len(ordered_nodes)))


def extract_article_document(soup) -> dict[str, str]:
    """Return separated title, subtitle, and body fields from a publisher page."""
    title = _page_title(soup)
    title_node = soup.find("h1")
    subtitle_nodes = _page_subtitle_nodes(soup, title)
    subtitle_parts = list(dict.fromkeys(
        text for node in subtitle_nodes if (text := _subtitle_text(node, title))
    ))
    subtitle = "\n".join(subtitle_parts)

    # Some publishers place the headline and deck inside the same article root.
    # Remove only those identified nodes, leaving duplicated lead copy untouched.
    if title_node is not None and title_node.parent is not None:
        title_node.decompose()
    for subtitle_node in subtitle_nodes:
        if subtitle_node.parent is not None:
            subtitle_node.decompose()

    body, method = extract_article_text(soup)
    # A publisher may duplicate its headline as plain text inside the chosen
    # body container. Remove only an exact standalone heading at the start.
    body_lines = body.splitlines()
    if body_lines and re.sub(r"\s+", "", body_lines[0]).casefold() == re.sub(r"\s+", "", title).casefold():
        body = "\n".join(body_lines[1:])
    return {"title": title, "subtitle": subtitle, "body": body, "load_method": method}

def load_article(url: str = "", pasted_text: str = ""):
    url, pasted_text = (url or "").strip(), (pasted_text or "").strip()
    if pasted_text:
        pasted_text = _clean_article_lines(pasted_text.splitlines())
        if len(pasted_text) < 120:
            raise ValueError("기사 본문이 너무 짧습니다. 본문을 충분히 붙여넣어 주세요.")
        return pasted_text, {
            "source": url or "직접 입력", "title": "(제목 없음)", "subtitle": "", "load_method": "manual",
        }
    if not url:
        raise ValueError("기사 URL 또는 기사 본문이 필요합니다.")
    if not valid_remote_url(url):
        raise ValueError("올바른 공개 http(s) 기사 URL을 입력해 주세요.")
    try:
        response=requests.get(url,headers={
            'User-Agent':'Mozilla/5.0 (compatible; PharmaMate/2.2)',
            'Accept-Language':'ko-KR,ko;q=0.9,en;q=0.8'
        },timeout=(10,30))
        response.raise_for_status()
        if not valid_remote_url(response.url):
            raise ValueError('기사 주소가 허용되지 않는 위치로 연결되었습니다.')
        soup=BeautifulSoup(response.content,'html.parser')
        document = extract_article_document(soup)
        metadata = {
            "source": url,
            "title": document["title"],
            "subtitle": document["subtitle"],
            "load_method": document["load_method"],
        }
        return document["body"], metadata
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("URL에서 기사 본문을 가져오지 못했습니다. 기사 본문을 직접 붙여넣어 주세요. "
                         f"(원인: {type(exc).__name__})") from exc

def article_id_for(text: str, url: str = "") -> str:
    return hashlib.sha256(((url or "") + "\n" + text).encode("utf-8")).hexdigest()[:20]
