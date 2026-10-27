"""Images and pages for AI tools: public links, inline base64, or short-lived uploads."""
import base64
from collections import OrderedDict
from html.parser import HTMLParser
import ipaddress
import re
import secrets
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from .config import MAX_FILE_BYTES

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
MAX_PAGE_BYTES = 5 * 1024 * 1024


class Uploads:
    """Files an AI client posts to /api/uploads and then references as upload:<id>; held in memory for an hour."""
    ttl, limit, budget = 3600, 100, 300 * 1024 * 1024

    def __init__(self):
        self.items = OrderedDict()
        self.lock = threading.Lock()

    def add(self, data):
        key = f"upload:{secrets.token_hex(16)}"
        with self.lock:
            self._expire()
            self.items[key] = (time.monotonic() + self.ttl, data)
            while len(self.items) > self.limit or sum(len(d) for _, d in self.items.values()) > self.budget:
                self.items.popitem(last=False)
        return key

    def get(self, key):
        with self.lock:
            self._expire()
            item = self.items.get(key)
        if item is None:
            raise ValueError(f"{key} 不存在或已过期，上传后 1 小时内有效")
        return item[1]

    def _expire(self):
        now = time.monotonic()
        for key in [key for key, (expires, _) in self.items.items() if expires < now]:
            del self.items[key]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # Each hop is re-checked in fetch().


OPENER = urllib.request.build_opener(NoRedirect)


def check_public(url):
    """Only public internet hosts; the server must never be steered into the local network."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError("只支持 http(s) 链接")
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"无法解析域名 {parts.hostname}") from exc
    if any(not ipaddress.ip_address(info[4][0].split("%")[0]).is_global for info in infos):
        raise ValueError("不能访问内网或本机地址")


def fetch(url, limit=MAX_FILE_BYTES, accept="image/*,*/*;q=0.5"):
    """Return (bytes, charset, final url)."""
    for _ in range(5):
        check_public(url)
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
        try:
            response = OPENER.open(request, timeout=20)
        except urllib.error.HTTPError as exc:
            if exc.code in {301, 302, 303, 307, 308} and exc.headers.get("Location"):
                url = urllib.parse.urljoin(url, exc.headers["Location"])
                continue
            raise ValueError(f"下载失败：HTTP {exc.code}") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise ValueError(f"下载失败：{getattr(exc, 'reason', exc)}") from exc
        with response:
            data = response.read(limit + 1)
            if len(data) > limit:
                raise ValueError(f"文件超过 {limit // 1024 // 1024} MB")
            return data, response.headers.get_content_charset(), url
    raise ValueError("下载失败：重定向次数过多")


def load_image(source, uploads):
    """Raw bytes for an http(s) link, a data:image/...;base64 URI or an upload:<id>."""
    if not isinstance(source, str) or not source.strip():
        raise ValueError("图片来源不能为空")
    source = source.strip()
    if source.startswith("upload:"):
        return uploads.get(source)
    if source.startswith("data:"):
        header, _, payload = source.partition(",")
        if ";base64" not in header:
            raise ValueError("data 链接须为 base64 编码")
        if len(payload) > MAX_FILE_BYTES * 4 // 3 + 4:
            raise ValueError("每张图片不能超过 20 MB")
        try:
            return base64.b64decode(payload, validate=True)
        except ValueError as exc:
            raise ValueError("base64 内容无效") from exc
    if source.startswith(("http://", "https://")):
        return fetch(source)[0]
    raise ValueError("图片来源须为 http(s) 链接、data:image/...;base64,... 或 upload:<id>")


class PageParser(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "template"}

    def __init__(self, base):
        super().__init__(convert_charrefs=True)
        self.base, self.title, self.text, self.images = base, "", [], {}
        self.skipping, self.in_title = 0, False

    def handle_starttag(self, tag, attrs):
        attrs = {key: value or "" for key, value in attrs}
        if tag in self.SKIP:
            self.skipping += 1
        elif tag == "title":
            self.in_title = True
        elif tag == "meta" and (attrs.get("property") or attrs.get("name")) in {"og:image", "twitter:image"}:
            self.image(attrs.get("content", ""), "页面主图")
        elif tag == "img":
            # Lazy-loading galleries keep the real address in data-* attributes.
            src = next((attrs[key] for key in ("data-src", "data-original", "data-lazy-src", "src") if attrs.get(key)), "")
            self.image(src, attrs.get("alt", ""))

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skipping:
            self.skipping -= 1
        elif tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.skipping:
            return
        if self.in_title:
            self.title += data
        elif data.strip():
            self.text.append(" ".join(data.split()))

    def image(self, src, alt):
        src = src.strip()
        if not src or src.startswith("data:"):
            return
        url = urllib.parse.urljoin(self.base, "https:" + src if src.startswith("//") else src)
        if url.startswith(("http://", "https://")):
            self.images.setdefault(url, alt.strip()[:100])


SCRIPT_IMAGE = re.compile(r"(?:https?:)?//[^\s\"'<>()]+?\.(?:jpe?g|png|webp)(?:_[^\s\"'<>()]*)?", re.I)


def read_page(url, max_text=6000, max_images=80):
    """Title, visible text and image addresses, including gallery images that pages keep in scripts."""
    data, charset, final = fetch(url, MAX_PAGE_BYTES, "text/html,application/xhtml+xml,*/*;q=0.5")
    if not charset:
        found = re.search(rb"<meta[^>]+charset=[\"']?([\w-]+)", data[:4096], re.I)
        charset = found.group(1).decode() if found else "utf-8"
    try:
        html = data.decode(charset, errors="replace")
    except LookupError:
        html = data.decode("utf-8", errors="replace")
    return parse_page(html, final, max_text, max_images)


def parse_page(html, base, max_text=6000, max_images=80):
    parser = PageParser(base)
    parser.feed(html)
    for match in SCRIPT_IMAGE.findall(html.replace("\\/", "/")):
        parser.image(match, "页面脚本中的图片")
    text = "\n".join(parser.text)
    return {"url": base, "title": " ".join(parser.title.split()), "text": text[:max_text], "textTruncated": len(text) > max_text,
            "images": [{"url": key, "alt": alt} for key, alt in list(parser.images.items())[:max_images]]}
