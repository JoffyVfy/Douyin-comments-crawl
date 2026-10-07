
from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import List

from scraper_plugin.douyin import DouyinCommentScraper
from scraper_plugin.excel import export_video_comments_to_excel


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="批量抓取指定抖音视频链接的评论区内容并导出为 Excel"
    )
    parser.add_argument(
        "links",
        nargs="*",
        help="一个或多个抖音视频链接（完整链接 / 分享短链 / 纯视频 ID）",
    )
    parser.add_argument(
        "--links-file",
        default=None,
        help="视频链接清单文件路径（每行一个链接，# 开头的行会被忽略）",
    )
    parser.add_argument(
        "--output",
        default="result/douyin_comments.xlsx",
        help="导出的 Excel 文件路径 (默认: result/douyin_comments.xlsx)",
    )
    parser.add_argument(
        "--storage-state",
        default=None,
        help="Playwright 的 storage state JSON 文件路径 (用于复用登录态)",
    )
    parser.add_argument(
        "--show-browser",
        action="store_true",
        help="显示浏览器窗口 (默认无头模式运行)",
    )
    parser.add_argument(
        "--max-comment-pages",
        type=int,
        default=50,
        help="单个视频最多抓取的评论分页数",
    )
    parser.add_argument(
        "--max-reply-pages",
        type=int,
        default=10,
        help="单条评论的回复分页上限",
    )
    parser.add_argument(
        "--comment-page-size",
        type=int,
        default=20,
        help="每次请求的顶层评论数量",
    )
    parser.add_argument(
        "--reply-page-size",
        type=int,
        default=20,
        help="每次请求的回复数量",
    )
    parser.add_argument(
        "--pause-seconds",
        type=float,
        default=0.6,
        help="接口请求之间的等待秒数",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="日志级别 (DEBUG/INFO/WARNING/ERROR)",
    )
    return parser.parse_args()


def collect_links(args: argparse.Namespace) -> List[str]:
    """合并命令行链接与链接文件中的链接，去重并保持顺序。"""
    links: List[str] = [link.strip() for link in args.links if link.strip()]
    if args.links_file:
        path = Path(args.links_file).expanduser()
        if not path.exists():
            raise FileNotFoundError(f"链接文件不存在: {path}")
        try:
            content = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            content = path.read_text(encoding="gbk")
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            links.append(line)
    unique: List[str] = []
    seen: set[str] = set()
    for link in links:
        if link not in seen:
            seen.add(link)
            unique.append(link)
    return unique


def main() -> None:
    args = parse_arguments()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    try:
        links = collect_links(args)
    except FileNotFoundError as exc:
        logging.error(str(exc))
        raise SystemExit(1)

    if not links:
        logging.error("未提供任何视频链接：请在命令行直接传入链接，或使用 --links-file 指定链接文件")
        raise SystemExit(1)

    logging.info("共 %d 个视频待抓取", len(links))

    scraper = DouyinCommentScraper(
        links,
        headless=not args.show_browser,
        storage_state=args.storage_state,
        comment_page_size=args.comment_page_size,
        reply_page_size=args.reply_page_size,
        max_comment_pages=args.max_comment_pages,
        max_reply_pages=args.max_reply_pages,
        pause_seconds=args.pause_seconds,
    )

    videos = scraper.scrape()
    output_path = export_video_comments_to_excel(videos, args.output)
    logging.info("抓取完成，结果已写入 %s", output_path)


if __name__ == "__main__":
    main()

