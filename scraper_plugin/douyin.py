
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse

from playwright.sync_api import Browser, Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

__all__ = [
    "CommentRecord",
    "VideoRecord",
    "DouyinCommentScraper",
]


_AWEME_ID_RE = re.compile(r"\d{15,}")

# 增量滚动页面，尽量触发虚拟列表加载更多评论。
_SCROLL_JS = r"""
() => {
    const rc = document.querySelector('.route-scroll-container');
    if (rc) rc.scrollTop += 500;
    [...document.querySelectorAll('*')].filter((e) => e.scrollHeight > e.clientHeight)
        .forEach((e) => { e.scrollTop += 500; });
}
"""

# 点击“展开回复”并按文档顺序提取每个顶层评论的直接回复文字。
_REPLY_EXTRACT_JS = r"""
async () => {
    const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
    document.querySelectorAll('button.comment-reply-expand-btn').forEach((b) => b.click());
    await sleep(3000);
    const leafTexts = (el) => [...el.querySelectorAll('*')]
        .filter((k) => k.childElementCount === 0)
        .map((k) => (k.innerText || '').trim())
        .filter(Boolean);
    const nodes = [...document.querySelectorAll('.comment-mainContent, .replyContainer')];
    const groups = [];
    let current = null;
    for (const node of nodes) {
        const cls = (node.className || '').toString();
        if (cls.includes('comment-mainContent')) {
            current = [];
            groups.push(current);
        } else if (cls.includes('replyContainer')) {
            if (node.parentElement && node.parentElement.closest('.replyContainer')) continue;
            const texts = leafTexts(node);
            const candidates = texts.filter((t) =>
                t !== '...' && t !== '分享' && t !== '回复' &&
                !t.startsWith('展开') && !/^\d+$/.test(t) &&
                !/(天|周|月|年|小时|分钟|秒)前/.test(t)
            );
            const replyText = candidates.slice(1).sort((a, b) => b.length - a.length)[0] || '';
            if (replyText && current) current.push(replyText);
        }
    }
    return groups;
}
"""


@dataclass
class CommentRecord:
    comment_id: str
    author_id: str
    text: str
    replies: List[str] = field(default_factory=list)


@dataclass
class VideoRecord:
    aweme_id: str
    title: str
    comments: List[CommentRecord] = field(default_factory=list)


class DouyinApiError(RuntimeError):
    """Raised when a Douyin API call fails."""


class DouyinCommentScraper:
    """Fetch comment data for a list of Douyin video links.

    说明：抖音的接口现在对“手动 fetch”会返回空响应，但对页面自己发出的
    请求正常放行。因此本实现不再手动拼 URL 发请求，而是：
      1. 打开视频页后，监听页面自己发出的 ``comment/list`` 请求并收集其 JSON；
      2. 通过滚动评论区触发页面加载更多评论；
      3. 回复接口响应已加密，改为点击“展开回复”后从页面 DOM 提取回复文字。
    """

    def __init__(
        self,
        video_links: List[str],
        *,
        headless: bool = True,
        storage_state: Optional[str] = None,
        comment_page_size: int = 20,
        reply_page_size: int = 20,
        max_comment_pages: int = 50,
        max_reply_pages: int = 10,
        pause_seconds: float = 0.6,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.video_links = [link.strip() for link in video_links if link.strip()]
        self.headless = headless
        self.storage_state_path = Path(storage_state).expanduser() if storage_state else None
        self.comment_page_size = comment_page_size
        self.reply_page_size = reply_page_size
        self.max_comment_pages = max_comment_pages
        self.max_reply_pages = max_reply_pages
        self.pause_seconds = pause_seconds
        self.logger = logger or logging.getLogger(__name__)

    def scrape(self) -> List[VideoRecord]:
        """Run the scraper and return the collected data."""
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=self.headless)
            try:
                context = self._build_context(browser)
                try:
                    page = context.new_page()
                    return self._scrape_with_page(page)
                finally:
                    context.close()
            finally:
                browser.close()

    def _build_context(self, browser: Browser):
        kwargs = {
            "viewport": {"width": 1280, "height": 900},
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/119.0.0.0 Safari/537.36"
            ),
            "locale": "zh-CN",
        }
        if self.storage_state_path:
            if not self.storage_state_path.exists():
                raise FileNotFoundError(f"Storage state file not found: {self.storage_state_path}")
            kwargs["storage_state"] = str(self.storage_state_path)
        return browser.new_context(**kwargs)

    def _scrape_with_page(self, page: Page) -> List[VideoRecord]:
        results: List[VideoRecord] = []
        seen: set[str] = set()
        total = len(self.video_links)
        for index, link in enumerate(self.video_links, start=1):
            try:
                url = self._normalise_video_url(link)
            except DouyinApiError as exc:
                self.logger.warning("[%d/%d] 跳过无法识别的链接: %s (%s)", index, total, link, exc)
                continue

            if url in seen:
                self.logger.warning("[%d/%d] 跳过重复链接: %s", index, total, link)
                continue
            seen.add(url)
            self.logger.info("[%d/%d] 正在打开 %s", index, total, url)

            collected: List[Dict[str, object]] = []
            seen_cids: set[str] = set()
            no_more = {"value": False}

            def on_response(resp) -> None:
                try:
                    resp_url = resp.url
                    if "comment/list" not in resp_url or "reply" in resp_url:
                        return
                    try:
                        body = resp.json()
                    except Exception:
                        return
                    if not isinstance(body, dict) or body.get("status_code") != 0:
                        return
                    for comment in (body.get("comments") or []):
                        if not isinstance(comment, dict):
                            continue
                        cid = comment.get("cid", "")
                        if cid and cid not in seen_cids:
                            seen_cids.add(cid)
                            collected.append(comment)
                    if not body.get("has_more"):
                        no_more["value"] = True
                except Exception:
                    return

            def handle_route(route) -> None:
                route_url = route.request.url
                if "comment/list" in route_url and "reply" not in route_url:
                    route.continue_(url=re.sub(r"count=\d+", "count=50", route_url))
                    return
                route.continue_()

            page.route("**/*", handle_route)
            page.on("response", on_response)
            try:
                try:
                    page.goto(url, wait_until="domcontentloaded")
                    try:
                        page.wait_for_load_state("networkidle", timeout=10_000)
                    except PlaywrightTimeoutError:
                        self.logger.warning("页面网络持续繁忙，继续执行")

                    aweme_id = self._extract_aweme_id(page.url)
                    if not aweme_id:
                        self.logger.error("[%d/%d] 无法从 %s 解析视频 ID，已跳过", index, total, link)
                        continue

                    title = self._title_from_page(page, aweme_id)
                    self.logger.info("[%d/%d] 正在抓取评论: %s (%s)", index, total, aweme_id, title)
                    self._scroll_comment_panel(page, collected, no_more)
                finally:
                    try:
                        page.unroute("**/*", handle_route)
                    except Exception:
                        pass
                    try:
                        page.remove_listener("response", on_response)
                    except Exception:
                        pass

                comments = [
                    CommentRecord(
                        comment_id=str(comment.get("cid", "")),
                        author_id=self._resolve_user_id(comment.get("user", {})),
                        text=str(comment.get("text", "")),
                    )
                    for comment in collected
                ]
                self.logger.info("[%d/%d] 评论抓取完成，共 %d 条", index, total, len(comments))
                self._attach_replies_from_dom(page, comments)
                results.append(VideoRecord(aweme_id=aweme_id, title=title, comments=comments))
            except Exception as exc:
                self.logger.error("[%d/%d] 该视频抓取失败，已跳过: %s (%s)", index, total, link, exc)

            time.sleep(self.pause_seconds)
        return results

    def _normalise_video_url(self, link: str) -> str:
        link = link.strip()
        if link.startswith("http://") or link.startswith("https://"):
            parsed = urlparse(link)
            path = parsed.path or ""
            if "/video/" in path or "/note/" in path:
                return link
            match = _AWEME_ID_RE.search(parsed.query)
            if match:
                return f"https://www.douyin.com/video/{match.group(0)}"
            return link
        if link.isdigit():
            return f"https://www.douyin.com/video/{link}"
        raise DouyinApiError(f"无法识别的视频链接: {link}")

    def _extract_aweme_id(self, url: str) -> Optional[str]:
        parsed = urlparse(url)
        parts = [part for part in parsed.path.split("/") if part]
        for i, part in enumerate(parts):
            if part in ("video", "note") and i + 1 < len(parts) and parts[i + 1].isdigit():
                return parts[i + 1]
        for part in reversed(parts):
            if part.isdigit():
                return part
        match = _AWEME_ID_RE.search(parsed.path)
        return match.group(0) if match else None

    def _title_from_page(self, page: Page, aweme_id: str) -> str:
        try:
            title = (page.title() or "").strip()
            for suffix in (" - 抖音精选", " - 抖音", " - 抖音网页版"):
                if title.endswith(suffix):
                    title = title[: -len(suffix)].strip()
                    break
            if title:
                return title
        except Exception as exc:
            self.logger.warning("获取视频标题失败 (%s)，使用默认标题", exc)
        return f"视频{aweme_id}"

    def _scroll_comment_panel(
        self,
        page: Page,
        collected: List[Dict[str, object]],
        no_more: Dict[str, bool],
    ) -> None:
        target = self.comment_page_size * self.max_comment_pages
        last_logged = 0
        for _ in range(120):
            if no_more["value"] or len(collected) >= target:
                break
            page.evaluate(_SCROLL_JS)
            page.wait_for_timeout(1000)
            count = len(collected)
            if count >= last_logged + 5:
                last_logged = (count // 5) * 5
                self.logger.info("已抓取 %d 条评论", last_logged)

    def _attach_replies_from_dom(self, page: Page, comments: List[CommentRecord]) -> None:
        """从页面 DOM 抓取回复（尽力而为），按顺序回填到 comments。"""
        if not comments:
            return
        try:
            groups = page.evaluate(_REPLY_EXTRACT_JS)
        except Exception as exc:
            self.logger.warning("从页面抓取回复失败，跳过回复: %s", exc)
            return
        if not isinstance(groups, list):
            return
        matched = 0
        for index, group in enumerate(groups):
            if index >= len(comments):
                break
            if group:
                comments[index].replies = [str(item) for item in group if item]
                matched += 1
        if matched:
            self.logger.info("已从页面抓取 %d 条评论的回复", matched)

    def _resolve_user_id(self, user_data: Dict[str, object]) -> str:
        for key in ("unique_id", "short_id", "display_id", "uid"):
            value = user_data.get(key)
            if isinstance(value, str) and value:
                return value
            if isinstance(value, int):
                return str(value)
        nickname = user_data.get("nickname")
        if isinstance(nickname, str) and nickname:
            return nickname
        return "未知用户"
