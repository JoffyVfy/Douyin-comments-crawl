# -*- coding: utf-8 -*-
"""把各种抖音分享链接统一转成规范视频链接。

支持识别：
  - https://www.douyin.com/video/7651177429838417204        （已是规范格式）
  - https://www.douyin.com/user/MS4w...?modal_id=7655...    （个人主页带 modal_id）
  - .../user/...?aweme_id=7655... 或 ...?item_id=7655...     （其它参数名）
  - 7651177429838417204                                      （纯视频 ID）

用法：
  python change_format.py                       # 读 links/test.txt，输出 links/converted_links.txt
  python change_format.py 输入.txt               # 读指定文件，输出 links/converted_links.txt
  python change_format.py 输入.txt 输出.txt      # 指定输入和输出文件

说明：短链（v.douyin.com/xxx）需要联网跳转才能解析，本脚本暂不处理，
     遇到时会跳过并在屏幕上提示。
"""
import re
import sys
from pathlib import Path

# 抖音视频 ID 是 15 位以上的纯数字
_VIDEO_ID_RE = re.compile(r"\d{15,}")

# 项目根目录与 links 文件夹（脚本位于 change_format/ 下）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_LINKS_DIR = _PROJECT_ROOT / "links"


def extract_video_id(text: str) -> str:
    """从一段文本里提取视频 ID，返回纯数字；找不到返回空字符串。"""
    # 1) 优先从已知参数里取（modal_id / aweme_id / item_id）
    for key in ("modal_id", "aweme_id", "item_id"):
        match = re.search(rf"[?&]{key}=(\d+)", text)
        if match and len(match.group(1)) >= 15:
            return match.group(1)
    # 2) 从 /video/ 或 /note/ 路径里取
    match = re.search(r"/(?:video|note)/(\d+)", text)
    if match:
        return match.group(1)
    # 3) 兜底：任意 15 位以上数字
    match = _VIDEO_ID_RE.search(text)
    return match.group(0) if match else ""


def convert_line(line: str) -> str:
    """把一行链接转成规范视频链接；无法识别返回空字符串。"""
    line = line.strip()
    if not line:
        return ""
    # 纯数字 ID
    if line.isdigit():
        return f"https://www.douyin.com/video/{line}"
    video_id = extract_video_id(line)
    if video_id:
        return f"https://www.douyin.com/video/{video_id}"
    return ""


def main() -> None:
    input_path = Path(sys.argv[1]) if len(sys.argv) > 1 else _LINKS_DIR / "test.txt"
    output_path = Path(sys.argv[2]) if len(sys.argv) > 2 else _LINKS_DIR / "converted_links.txt"

    if not input_path.exists():
        print(f"输入文件不存在: {input_path}")
        raise SystemExit(1)

    try:
        content = input_path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        content = input_path.read_text(encoding="gbk")

    converted: list[str] = []
    skipped: list[str] = []
    for raw in content.splitlines():
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            continue
        result = convert_line(raw)
        if result:
            converted.append(result)
        else:
            skipped.append(raw)

    # 去重并保持顺序
    unique: list[str] = []
    seen: set[str] = set()
    for link in converted:
        if link not in seen:
            seen.add(link)
            unique.append(link)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(unique) + ("\n" if unique else ""), encoding="utf-8")
    print(f"转换完成：{len(unique)} 条链接已写入 {output_path}")

    if skipped:
        print(f"跳过 {len(skipped)} 条无法识别的链接（可能是短链）：")
        for item in skipped:
            print(f"  - {item}")


if __name__ == "__main__":
    main()
