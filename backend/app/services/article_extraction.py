"""기사 URL 보안 검사와 본문 추출/정규화를 담당합니다."""
from __future__ import annotations

import hashlib
import json
import re
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

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
    '#article-view-content-div', '[itemprop="articleBody"]',
    '#articleBody', '#article_body', '#article-body',
    '.news-article-body', '.story-body', '.entry-content', '.post-content',
    '.article-view-content', '.article_view_content', '.article-body',
    '.article_body', '.news-view-content', '.article-content', '.article_view', 'article'
]
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
    '[class*="related"]', '[id*="related"]', '[class*="recommend"]',
    '[id*="recommend"]', '[class*="advert"]', '[id*="advert"]',
    '[aria-label*="관련 기사"]'
]

def _clean_article_node(node) -> str:
    fragment=BeautifulSoup(str(node),'html.parser')
    for selector in ARTICLE_NOISE_SELECTORS:
        for unwanted in fragment.select(selector):
            unwanted.decompose()
    lines=[]
    for line in fragment.get_text('\n',strip=True).splitlines():
        line=re.sub(r'\s+',' ',line).strip()
        if line and (not lines or line != lines[-1]):
            lines.append(line)
    return '\n'.join(lines)

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

def load_article(url: str = "", pasted_text: str = ""):
    url, pasted_text = (url or "").strip(), (pasted_text or "").strip()
    if pasted_text:
        if len(pasted_text) < 120:
            raise ValueError("기사 본문이 너무 짧습니다. 본문을 충분히 붙여넣어 주세요.")
        return pasted_text, {"source": url or "직접 입력", "title": "(제목 없음)", "load_method": "manual"}
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
        text,method=extract_article_text(soup)
        metadata={'source':url,'title':_page_title(soup),'load_method':method}
        return text,metadata
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("URL에서 기사 본문을 가져오지 못했습니다. 기사 본문을 직접 붙여넣어 주세요. "
                         f"(원인: {type(exc).__name__})") from exc

def article_id_for(text: str, url: str = "") -> str:
    return hashlib.sha256(((url or "") + "\n" + text).encode("utf-8")).hexdigest()[:20]
