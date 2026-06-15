import asyncio
import html
import base64
import time
from datetime import datetime
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional

try:
    import aiohttp
except ImportError:
    raise ImportError("缺少依赖: pip install aiohttp")

try:
    from playwright.async_api import async_playwright
except ImportError:
    raise ImportError("缺少依赖: pip install playwright && playwright install chromium")

from .model import Quote, Comment


# --- 单人语录合集：明亮杂志 / 语录书 风格 (宽度 1600px) ---
MAGAZINE_CSS = """
    * { box-sizing: border-box; margin: 0; padding: 0; }

    body {
        margin: 0;
        background: #f7f4ec;
        -webkit-font-smoothing: antialiased;
        -moz-osx-font-smoothing: grayscale;
        overflow: hidden;
    }

    .mag {
        width: 100%;
        background: #f7f4ec;
        font-family: 'Noto Sans SC', 'Source Han Sans SC', 'Microsoft YaHei',
                     'PingFang SC', -apple-system, sans-serif;
        color: #1c1a17;
    }

    .mag-serif {
        font-family: Georgia, 'Times New Roman', 'Source Han Serif SC',
                     'Noto Serif SC', 'Songti SC', serif;
    }

    .mag-header {
        padding: 96px 96px 64px 96px;
        border-bottom: 3px solid #e3ddcd;
    }

    .mag-kicker {
        font-family: Georgia, 'Times New Roman', serif;
        font-size: 32px;
        letter-spacing: 10px;
        color: #b08a3e;
        font-weight: 700;
    }

    .mag-title {
        font-size: 90px;
        font-weight: 700;
        color: #1c1a17;
        margin-top: 18px;
        line-height: 1.15;
        word-break: break-word;
    }

    .mag-title .m-name { color: #b08a3e; }

    .mag-sub {
        font-size: 34px;
        color: #a89f8a;
        margin-top: 22px;
        letter-spacing: 1px;
    }

    .mag-item {
        display: flex;
        gap: 54px;
        padding: 66px 96px;
        border-bottom: 2px solid #ece6d7;
        align-items: flex-start;
    }

    .mag-item:last-of-type { border-bottom: none; }

    .mag-num {
        font-size: 104px;
        font-weight: 700;
        color: #dacfb3;
        line-height: 0.9;
        min-width: 160px;
        flex-shrink: 0;
    }

    .mag-body { flex: 1; min-width: 0; }

    .mag-text {
        font-size: 60px;
        line-height: 1.5;
        color: #24211c;
        word-break: break-word;
        white-space: pre-wrap;
    }

    .mag-meta {
        font-size: 32px;
        color: #a89f8a;
        margin-top: 22px;
        letter-spacing: 1px;
    }

    .mag-meta .dot { margin: 0 16px; color: #cdbf9f; }
    .mag-src { color: #b08a3e; }

    .mag-cmt {
        margin-top: 28px;
        font-size: 36px;
        line-height: 1.6;
        color: #6f6552;
        background: #efe9d8;
        border-left: 6px solid #c9b27a;
        padding: 24px 34px;
        border-radius: 0 14px 14px 0;
    }

    .mag-cmt + .mag-cmt { margin-top: 14px; }
    .mag-cmt b { color: #a9863c; font-weight: 700; }

    .mag-footer {
        padding: 48px 96px 64px 96px;
        background: #f2eede;
        border-top: 3px solid #e3ddcd;
        display: flex;
        justify-content: space-between;
        align-items: center;
        font-size: 28px;
        color: #b3a98f;
    }

    .mag-footer .fp { font-weight: 700; letter-spacing: 1px; }

    /* ---- 单卡 (/语录) ---- */
    .mag-sc-top { padding: 96px 100px 0 100px; }
    .mag-sc-user {
        display: flex; align-items: center; gap: 38px;
        margin: 30px 0 8px 0;
    }
    .mag-sc-av {
        width: 160px; height: 160px; border-radius: 50%;
        object-fit: cover; border: 5px solid #ffffff;
        box-shadow: 0 8px 22px rgba(0,0,0,0.18); background: #e6dec9;
        flex-shrink: 0;
    }
    .mag-sc-name {
        font-size: 64px; font-weight: 700; color: #b08a3e; line-height: 1.1;
        word-break: break-word;
    }
    .mag-sc-uid { font-size: 30px; color: #a89f8a; margin-top: 10px; }
    .mag-sc-quote { padding: 0 100px; position: relative; }
    .mag-sc-qmark {
        font-family: Georgia, 'Times New Roman', serif;
        font-size: 240px; line-height: 0.7; color: #e4dabc;
        display: block; height: 130px;
    }
    .mag-sc-text {
        font-size: 84px; font-weight: 600; line-height: 1.4; color: #24211c;
        margin-top: 8px; white-space: pre-wrap; word-break: break-word;
    }
    .mag-sc-body { padding: 24px 100px 72px 100px; }
    .mag-sc-meta {
        font-size: 33px; color: #a89f8a; margin-top: 40px;
        letter-spacing: 1px; display: flex; align-items: center;
    }
    .mag-idx {
        font-family: Georgia, 'Times New Roman', serif; font-weight: 700;
        color: #b08a3e; border: 3px solid #ddcfa8; border-radius: 999px;
        padding: 8px 28px; font-size: 32px; margin-right: 26px;
    }

    /* ---- 多人合集 (/语录 N) ---- */
    .mag-user-item {
        display: flex; gap: 46px; padding: 64px 100px;
        border-bottom: 2px solid #ece6d7; align-items: flex-start;
    }
    .mag-user-item:last-of-type { border-bottom: none; }
    .mag-user-av {
        width: 135px; height: 135px; border-radius: 50%; object-fit: cover;
        border: 4px solid #ffffff; box-shadow: 0 6px 18px rgba(0,0,0,0.16);
        background: #e6dec9; flex-shrink: 0;
    }
    .mag-user-body { flex: 1; min-width: 0; }
    .mag-user-top {
        display: flex; align-items: baseline; justify-content: space-between;
        gap: 24px;
    }
    .mag-user-name {
        font-size: 48px; font-weight: 700; color: #b08a3e; word-break: break-word;
    }
    .mag-user-num {
        font-size: 64px; font-weight: 700; color: #dacfb3; line-height: 1;
        flex-shrink: 0;
    }
    .mag-user-body .mag-text { margin-top: 14px; }
"""


class QuoteRenderer:
    """轻量高速版渲染"""

    DEFAULT_AVATAR_B64: str = ""
    _avatar_cache: Dict[str, Tuple[float, str]] = {}
    _avatar_cache_ttl = 24 * 60 * 60
    _playwright = None
    _browser = None
    _browser_lock = None

    @classmethod
    def init_resources(cls, plugin_dir: Path):
        possible_paths = [
            plugin_dir / "logo.png",
            plugin_dir / "assets" / "logo.png"
        ]

        for p in possible_paths:
            if p.exists():
                with open(p, "rb") as f:
                    cls.DEFAULT_AVATAR_B64 = (
                        "data:image/png;base64,"
                        + base64.b64encode(f.read()).decode()
                    )
                break

    @classmethod
    async def _get_browser(cls):
        if cls._browser_lock is None:
            cls._browser_lock = asyncio.Lock()

        async with cls._browser_lock:
            try:
                if cls._browser and cls._browser.is_connected():
                    return cls._browser
            except Exception:
                cls._browser = None

            if cls._playwright is None:
                cls._playwright = await async_playwright().start()

            cls._browser = await cls._playwright.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-extensions",
                    "--disable-background-networking",
                    "--disable-default-apps",
                    "--disable-sync",
                    "--disable-translate",
                    "--hide-scrollbars",
                    "--mute-audio",
                    "--font-render-hinting=none",
                ],
            )
            return cls._browser

    @classmethod
    async def shutdown(cls):
        try:
            if cls._browser:
                await cls._browser.close()
        except Exception:
            pass
        cls._browser = None

        try:
            if cls._playwright:
                await cls._playwright.stop()
        except Exception:
            pass
        cls._playwright = None

    @staticmethod
    async def html_to_png_bytes(
        html_content: str,
        options: Optional[Dict[str, Any]] = None
    ) -> bytes:
        """
        Playwright 渲染 HTML -> 图片。

        修改点：
        1. 不再等待远程字体。
        2. set_content 使用 domcontentloaded。
        3. screenshot 设置 timeout=0，避免卡在 waiting for fonts to load。
        """
        options = options or {}
        viewport = options.get("viewport", {"width": 1600, "height": 800})
        width = int(viewport.get("width", 1600))
        init_height = int(max(200, viewport.get("height", 800)))

        browser = await QuoteRenderer._get_browser()
        page = await browser.new_page(
            viewport={
                "width": width,
                "height": init_height
            }
        )

        try:
            await page.set_content(
                html_content,
                wait_until="domcontentloaded",
                timeout=15000
            )

            full_height = await page.evaluate(
                "Math.max(document.body.scrollHeight, document.documentElement.scrollHeight)"
            )

            full_height = int(min(max(full_height, 200), 12000))

            await page.set_viewport_size(
                {
                    "width": width,
                    "height": full_height
                }
            )

            return await page.screenshot(
                full_page=True,
                type="jpeg",
                quality=85,
                timeout=0
            )

        finally:
            await page.close()

    @staticmethod
    async def _fetch_avatar_b64(qq: str) -> str:
        if not qq or not qq.isdigit():
            return QuoteRenderer.DEFAULT_AVATAR_B64

        now = time.time()
        cached = QuoteRenderer._avatar_cache.get(qq)
        if cached and now - cached[0] < QuoteRenderer._avatar_cache_ttl:
            return cached[1]

        urls = [
            f"https://q1.qlogo.cn/g?b=qq&nk={qq}&s=100",
            f"https://q2.qlogo.cn/headimg_dl?dst_uin={qq}&spec=100",
            f"https://thirdqq.qlogo.cn/g?b=qq&nk={qq}&s=100",
        ]

        async with aiohttp.ClientSession() as session:
            for url in urls:
                try:
                    async with session.get(url, timeout=2.5) as resp:
                        if resp.status == 200:
                            data = await resp.read()
                            if len(data) > 500:
                                b64 = base64.b64encode(data).decode()
                                result = f"data:image/jpg;base64,{b64}"
                                QuoteRenderer._avatar_cache[qq] = (now, result)
                                return result
                except:
                    continue

        QuoteRenderer._avatar_cache[qq] = (now, QuoteRenderer.DEFAULT_AVATAR_B64)
        return QuoteRenderer.DEFAULT_AVATAR_B64

    @staticmethod
    def _get_time_text(created_at: float) -> str:
        dt = datetime.fromtimestamp(created_at)
        now = datetime.now()

        if dt.year == now.year:
            return dt.strftime("%m月%d日 %H:%M")

        return dt.strftime("%Y年%m月%d日 %H:%M")

    @staticmethod
    def _get_group_html(q: Quote, current_group_id: Optional[str] = None) -> str:
        if hasattr(q, "temp_source_label") and q.temp_source_label:
            if not current_group_id or str(q.group) != str(current_group_id):
                safe_group = html.escape(q.temp_source_label)
                return f'<span class="group-tag">{safe_group}</span>'

        return ""

    @staticmethod
    async def _prepare_comments_html(
        q: Quote,
        bot_qq: str = "10000",
        bot_name: str = "AI鉴赏家"
    ) -> str:
        display_comments = list(q.comments)

        if not display_comments and q.ai_reason:
            display_comments.append(
                Comment(
                    qq=str(bot_qq),
                    name=bot_name,
                    text=q.ai_reason,
                    created_at=q.created_at
                )
            )

        if not display_comments:
            return ""

        rows = []

        for c in display_comments[-5:]:
            c_name = html.escape(c.name)
            c_text = html.escape(c.text)

            rows.append(f"""
            <div class="comment-row">
                <div class="cmt-content">
                    <span class="cmt-name">{c_name}:</span>
                    {c_text}
                </div>
            </div>
            """)

        return f"""
        <div class="comments-section">
            {''.join(rows)}
        </div>
        """

    @staticmethod
    def _build_magazine_comments(
        q: Quote, bot_qq: str, bot_name: str
    ) -> str:
        """构造杂志风格的评论/AI 点评块（最多 3 条）。"""
        display_comments = list(q.comments)
        if not display_comments and q.ai_reason:
            display_comments.append(
                Comment(
                    qq=str(bot_qq),
                    name=bot_name,
                    text=q.ai_reason,
                    created_at=q.created_at,
                )
            )
        out = ""
        for c in display_comments[-3:]:
            out += (
                '<div class="mag-cmt">'
                f'<b>{html.escape(c.name)} ·</b> {html.escape(c.text)}'
                '</div>'
            )
        return out

    @staticmethod
    def _magazine_source_html(q: Quote, current_group_id: Optional[str]) -> str:
        """global 模式下的来源群标签（杂志风）。"""
        label = getattr(q, "temp_source_label", "")
        if label and (
            not current_group_id or str(q.group) != str(current_group_id)
        ):
            return (
                '<span class="dot">·</span>'
                f'<span class="mag-src">{html.escape(label)}</span>'
            )
        return ""

    @staticmethod
    async def render_single_card(
        q: Quote,
        index: int,
        total: int,
        current_group_id: Optional[str] = None,
        bot_qq: str = "10000",
        bot_name: str = "AI鉴赏家"
    ) -> Tuple[str, Dict[str, Any]]:
        """单条语录：明亮杂志 / 语录书 风格的特写页。"""
        avatar_b64 = await QuoteRenderer._fetch_avatar_b64(q.qq)

        safe_text = html.escape(q.text)
        safe_name = html.escape(q.name)
        time_text = QuoteRenderer._get_time_text(q.created_at)
        count_text = f"#{index} / {total}" if total > 0 else "AstrBot"

        src_html = QuoteRenderer._magazine_source_html(q, current_group_id)
        uid_html = (
            f'<div class="mag-sc-uid">{src_html}</div>' if src_html else ""
        )
        cmt_html = QuoteRenderer._build_magazine_comments(q, bot_qq, bot_name)

        gen_time = datetime.now().strftime("%Y-%m-%d %H:%M")
        plugin_info_text = "Menkelo/astrbot_plugin_quote_core"

        html_content = f"""
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                {MAGAZINE_CSS}
                body {{ width: 1600px; }}
            </style>
        </head>
        <body>
            <div class="mag">
                <div class="mag-sc-top">
                    <div class="mag-kicker">QUOTE</div>
                    <div class="mag-sc-user">
                        <img class="mag-sc-av" src="{avatar_b64}">
                        <div>
                            <div class="mag-sc-name">{safe_name}</div>
                            {uid_html}
                        </div>
                    </div>
                </div>
                <div class="mag-sc-quote">
                    <span class="mag-sc-qmark">&ldquo;</span>
                    <div class="mag-sc-text">{safe_text}</div>
                </div>
                <div class="mag-sc-body">
                    {cmt_html}
                    <div class="mag-sc-meta">
                        <span class="mag-idx">{count_text}</span>{time_text}
                    </div>
                </div>
                <div class="mag-footer">
                    <span class="fp">{plugin_info_text}</span>
                    <span>{gen_time}</span>
                </div>
            </div>
        </body>
        </html>
        """

        return html_content, {
            "full_page": True,
            "viewport": {"width": 1600, "height": 1},
        }

    @staticmethod
    async def _render_collection_magazine(
        quotes: List[Quote],
        title: str,
        self_qq: str,
        current_group_id: Optional[str] = None,
        bot_name: str = "AI鉴赏家",
    ) -> Tuple[str, Dict[str, Any]]:
        """单人语录合集：明亮杂志 / 语录书 风格。"""
        items_html = ""

        for i, q in enumerate(quotes):
            safe_text = html.escape(q.text)
            time_text = QuoteRenderer._get_time_text(q.created_at)

            src_html = QuoteRenderer._magazine_source_html(q, current_group_id)
            cmt_html = QuoteRenderer._build_magazine_comments(
                q, self_qq, bot_name
            )

            items_html += f"""
            <div class="mag-item">
                <div class="mag-num mag-serif">{i + 1:02d}</div>
                <div class="mag-body">
                    <div class="mag-text">{safe_text}</div>
                    <div class="mag-meta">{time_text}{src_html}</div>
                    {cmt_html}
                </div>
            </div>
            """

        # 标题：把人名高亮，"的随机语录" 保持深色
        suffix = "的随机语录"
        if suffix in title:
            name_part = title.rsplit(suffix, 1)[0]
            title_html = (
                f'<span class="m-name">{html.escape(name_part)}</span>{suffix}'
            )
        else:
            title_html = html.escape(title)

        sub_text = (
            f"已随机抽取 {len(quotes)} 条 · "
            f"{datetime.now().strftime('%Y-%m-%d')}"
        )
        gen_time = datetime.now().strftime("%Y-%m-%d %H:%M")
        plugin_info_text = "Menkelo/astrbot_plugin_quote_core"

        html_content = f"""
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                {MAGAZINE_CSS}
                body {{ width: 1600px; }}
            </style>
        </head>
        <body>
            <div class="mag">
                <div class="mag-header">
                    <div class="mag-kicker">QUOTE COLLECTION</div>
                    <div class="mag-title">{title_html}</div>
                    <div class="mag-sub">{sub_text}</div>
                </div>
                {items_html}
                <div class="mag-footer">
                    <span class="fp">{plugin_info_text}</span>
                    <span>{gen_time}</span>
                </div>
            </div>
        </body>
        </html>
        """

        return html_content, {
            "full_page": True,
            "viewport": {"width": 1600, "height": 1},
        }

    @staticmethod
    async def render_merged_card(
        quotes: List[Quote],
        title: str,
        self_qq: str,
        title_is_blue: bool = False,
        current_group_id: Optional[str] = None,
        bot_name: str = "AI鉴赏家"
    ) -> Tuple[str, Dict[str, Any]]:
        if not quotes:
            return "", {}

        # 单人语录合集 -> 明亮杂志 / 语录书 风格
        if title_is_blue:
            return await QuoteRenderer._render_collection_magazine(
                quotes,
                title,
                self_qq,
                current_group_id=current_group_id,
                bot_name=bot_name,
            )

        # 多人随机语录合集 -> 明亮杂志 / 语录书 风格（头像 + 人名）
        return await QuoteRenderer._render_collection_users_magazine(
            quotes,
            title,
            self_qq,
            current_group_id=current_group_id,
            bot_name=bot_name,
        )

    @staticmethod
    async def _render_collection_users_magazine(
        quotes: List[Quote],
        title: str,
        self_qq: str,
        current_group_id: Optional[str] = None,
        bot_name: str = "AI鉴赏家",
    ) -> Tuple[str, Dict[str, Any]]:
        """多人随机语录合集：明亮杂志风（每条带头像 + 人名）。"""
        qq_set = {q.qq for q in quotes}
        results = await asyncio.gather(
            *[QuoteRenderer._fetch_avatar_b64(uid) for uid in qq_set]
        )
        avatar_map = {uid: b64 for uid, b64 in zip(qq_set, results)}

        items_html = ""
        for i, q in enumerate(quotes):
            ava = avatar_map.get(q.qq, QuoteRenderer.DEFAULT_AVATAR_B64)
            safe_text = html.escape(q.text)
            safe_name = html.escape(q.name)
            time_text = QuoteRenderer._get_time_text(q.created_at)
            src_html = QuoteRenderer._magazine_source_html(q, current_group_id)
            cmt_html = QuoteRenderer._build_magazine_comments(
                q, self_qq, bot_name
            )

            items_html += f"""
            <div class="mag-user-item">
                <img class="mag-user-av" src="{ava}">
                <div class="mag-user-body">
                    <div class="mag-user-top">
                        <span class="mag-user-name">{safe_name}</span>
                        <span class="mag-user-num">{i + 1:02d}</span>
                    </div>
                    <div class="mag-text">{safe_text}</div>
                    <div class="mag-meta">{time_text}{src_html}</div>
                    {cmt_html}
                </div>
            </div>
            """

        title_html = html.escape(title)
        sub_text = f"已随机抽取 {len(quotes)} 条语录"
        gen_time = datetime.now().strftime("%Y-%m-%d %H:%M")
        plugin_info_text = "Menkelo/astrbot_plugin_quote_core"

        html_content = f"""
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                {MAGAZINE_CSS}
                body {{ width: 1600px; }}
            </style>
        </head>
        <body>
            <div class="mag">
                <div class="mag-header">
                    <div class="mag-kicker">QUOTE COLLECTION</div>
                    <div class="mag-title">{title_html}</div>
                    <div class="mag-sub">{sub_text}</div>
                </div>
                {items_html}
                <div class="mag-footer">
                    <span class="fp">{plugin_info_text}</span>
                    <span>{gen_time}</span>
                </div>
            </div>
        </body>
        </html>
        """

        return html_content, {
            "full_page": True,
            "viewport": {"width": 1600, "height": 1},
        }
