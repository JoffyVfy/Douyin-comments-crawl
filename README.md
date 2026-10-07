# 抖音评论采集

这个项目用来批量采集指定抖音视频的评论，供数据调研使用。完整流程分两步：

1. **整理链接**：把从创作者主页复制出来的各种链接，统一转成规范的视频链接。
2. **抓取评论**：打开这些视频页面，采集评论和回复，并导出到 Excel。

每个视频对应 Excel 里的一个工作表；每一行是一条评论，列为评论者 ID、评论正文和回复汇总。

## 1. 环境准备

1. 安装 Python 3.10 或更高版本。
2. 建议使用独立环境，避免和系统 Python 混用：

```powershell
conda create -n scrap_comments python=3.12
conda activate scrap_comments
```

3. 在项目根目录安装依赖：

```powershell
pip install -r requirements.txt
python -m playwright install
```

第二条命令会安装 Playwright 使用的 Chromium。每次重新打开终端后，都要先执行 `conda activate scrap_comments`。

## 2. 可选：保存登录态

若评论需要登录才能查看，可先保存一次登录状态，用于之后复用：

```
python -m playwright codegen https://www.douyin.com --save-storage douyin_state.json
```

命令运行时会弹出浏览器窗口，按照提示登录并关闭窗口即可生成 `douyin_state.json`。


## 3. 第一步：整理视频链接 (可选)

从抖音创作者主页打开视频时，复制出来的常常不是规范视频地址，而是带 `modal_id` 的主页链接。`change_format/change_format.py` 负责把这些链接统一成：

```text
https://www.douyin.com/video/视频ID
```

它能识别：

- `https://www.douyin.com/video/7651177429838417204`（已经是规范格式）
- `https://www.douyin.com/user/SEC_USER_ID?modal_id=7651177429838417204`（主页弹窗链接）
- 带 `aweme_id=` 或 `item_id=` 的链接
- `https://www.douyin.com/note/视频ID`
- 纯数字视频 ID

把收集到的链接放进 `links/test.txt`，每行一个；`#` 开头的行会被当作注释忽略。然后在项目根目录运行：

```powershell
python change_format/change_format.py
```

默认读取 `links/test.txt`，去重后写入 `links/converted_links.txt`。也可以指定输入和输出：

```powershell
python change_format/change_format.py 输入.txt
python change_format/change_format.py 输入.txt 输出.txt
```

`v.douyin.com` 短链需要联网跳转才能得到真实视频 ID，这个离线转换脚本不会处理，遇到时会跳过并提示。

## 4. 第二步：抓取评论

直接传入一个或多个视频链接：

```powershell
python main.py https://www.douyin.com/video/VIDEO_ID_1 https://www.douyin.com/video/VIDEO_ID_2 ^
    --storage-state douyin_state.json ^
    --output douyin_comments.xlsx
```

视频较多时，推荐把链接写入文本文件（每行一个链接，`#` 开头的行会被忽略），再用 `--links-file` 传入：

```powershell
python main.py --links-file links.txt ^
    --storage-state douyin_state.json ^
    --output douyin_comments.xlsx
```

支持的链接格式：

- 规范视频链接：`https://www.douyin.com/video/7651177429838417204`
- 规范图文链接：`https://www.douyin.com/note/7651177429838417204`
- 主页弹窗链接：`https://www.douyin.com/user/SEC_USER_ID?modal_id=7651177429838417204`
- 带 `aweme_id=` 或 `item_id=` 的链接
- 纯数字视频 ID

链接会自动去重。单个链接无法识别或抓取失败时会跳过，并继续处理后面的链接。

## 5. Excel 输出结构

每个视频对应 Excel 里的一个工作表；每一行是一条评论，列为评论者 ID、评论正文和回复汇总。

- 工作表名称来自视频标题，会自动去除非法字符并限制在 31 个字符内；重名时自动加后缀。
- 第 1 行表头为：评论者 ID、评论内容、回复内容。
- 回复内容按行拼接，保留换行和 emoji；纯图片、贴纸等非文字内容会被忽略。

## 6. 参数说明

| 参数 | 说明 |
| --- | --- |
| `links` | 直接写在命令行后面的一个或多个规范视频链接 |
| `--links-file` | 指向链接清单文本文件；每行一个链接，`#` 注释行会被忽略 |
| `--output` | Excel 输出路径，默认 `result/douyin_comments.xlsx` |
| `--storage-state` | Playwright 登录态 JSON 文件路径（首次可用） |
| `--show-browser` | 显示浏览器窗口，默认无界面运行 |
| `--comment-page-size` | 估算每个视频评论上限时用的初始页大小，默认 20 |
| `--max-comment-pages` | 与上一参数相乘得到最大评论数量，默认 50（约 1000 条） |
| `--pause-seconds` | 每完成一个视频后的等待秒数，默认 0.6 |
| `--log-level` | 日志级别：`DEBUG`、`INFO`、`WARNING`、`ERROR` |
| `--max-reply-pages` | 兼容参数，已被替换为直接从页面提取回复 |

## 7. 抓取原理

程序不自己发送评论接口请求。它会用 Playwright 打开规范视频页，监听页面自己发出的 `comment/list` 响应，并在用户滚动时触发评论继续加载。回复数据在接口中已被加密，因此程序会先在页面上点击“展开回复”，再从可见的 DOM 元素中提取回复文字。

## 8. 运行注意事项

- 先用 2 到 3 个链接配合 `--show-browser` 试运行，确认能看到评论后再批量处理。
- 抖音页面结构或接口随时可能变化；出现空数据时，通常需要对照最新页面调整抓取逻辑。
- 视频太多时容易触发风控，应增大 `--pause-seconds` 并分批运行。
- 登录失效、账号受限或请求过快也可能导致空结果，可重新生成登录态。
- 回复提取依赖当前页面结构，属于尽力抓取；页面改版后可能只拿到评论、拿不到回复。
- 程序不下载图片、视频或其他媒体文件。

## 9. 后续扩展

- 新增命令行参数以筛选发布时间、点赞数等条件。
- 支持断点续采或增量更新。

## 10. 发布到 GitHub 前

可以公开源代码、`requirements.txt` 和本说明。以下内容必须排除，且不能出现在 Git 历史中：

- `douyin_state.json`：登录 Cookie、令牌和私钥
- `links/`：真实视频链接清单
- `result/`、`extract_link/`：抓取结果、原始链接和调研表格
- `__pycache__/`：Python 缓存

仓库会保留目录示例，但不会包含真实调研数据：

- `links/test.txt.example`：虚构链接格式示例。使用前复制为 `links/test.txt`。
- `result/.gitkeep`：只用来保留输出目录，真实 Excel 会被忽略。

目录说明如下：

```text
.
├── main.py                         # 评论抓取入口
├── requirements.txt                # Python 依赖
├── .gitignore
├── change_format/
│   └── change_format.py            # 把各种链接转换成规范视频链接
├── scraper_plugin/
│   ├── douyin.py                   # 打开页面、监听评论并提取回复
│   └── excel.py                    # 导出 Excel
├── links/
│   ├── test.txt.example            # 可提交的虚构示例
│   ├── test.txt                    # 本地真实链接（不提交）
│   └── converted_links.txt         # 转换结果（不提交）
└── result/
    ├── .gitkeep                    # 保留空目录
    └── douyin_comments.xlsx        # 抓取结果（不提交）
```

## 11. 解决常见问题

| 问题 | 解决 |
| --- | --- |
| 启动时提示 Playwright 内核未安装 | 重新运行 `python -m playwright install` |
| 抓取为空或卡住 | 增加 `--pause-seconds` 或分批处理；查看日志确定卡在哪步 |
| 链接解析失败 | 确保用的是规范视频链接，或先运行 `change_format/change_format.py` 转换一下 |
| 回复提取为空 | 页面结构改版时会影响，尝试降低 `--comment-page-size` 观察 |