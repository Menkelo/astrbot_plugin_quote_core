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

    /* ---- 共享 token ---- */
    .mag-kicker {
        font-family: Georgia, 'Times New Roman', serif;
        font-size: 30px;
        letter-spacing: 11px;
        color: #b08a3e;
        font-weight: 700;
    }
    .mag-serif { font-family: Georgia, 'Times New Roman', serif; }
    .mag-src { color: #b08a3e; }
    .dot { margin: 0 16px; color: #cdbf9f; }

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
        padding: 48px 98px 60px 98px;
        background: #f2eede;
        border-top: 3px solid #e3ddcd;
    }
    .mag-footer .fp {
        font-size: 28px; color: #b3a98f; font-weight: 700; letter-spacing: 1px;
    }

    .mag-av {
        border-radius: 50%; object-fit: cover; background: #e6dec9;
        border: 6px solid #ffffff; box-shadow: 0 8px 24px rgba(0,0,0,0.18);
        flex-shrink: 0;
    }

    /* ============ B 单卡（右上头像 · 大字编辑风） ============ */
    .b-card { position: relative; overflow: hidden; padding: 104px 120px 70px 120px; }
    .b-wm {
        position: absolute; top: -70px; left: 32px;
        font-family: Georgia, 'Times New Roman', serif;
        font-size: 500px; line-height: 1; color: rgba(176,138,62,0.09);
        pointer-events: none; z-index: 0;
    }
    .b-top {
        display: flex; justify-content: space-between; align-items: flex-start;
        position: relative; z-index: 1;
    }
    .b-top-left { display: flex; flex-direction: column; gap: 30px; }
    .b-idx {
        font-family: Georgia, 'Times New Roman', serif; font-weight: 700;
        color: #b08a3e; border: 3px solid #ddcfa8; border-radius: 999px;
        padding: 10px 34px; font-size: 32px; align-self: flex-start;
    }
    .b-av { width: 210px; height: 210px; }
    .b-qtext {
        position: relative; z-index: 1; font-size: 100px; line-height: 1.42;
        font-weight: 700; color: #211e19; margin: 74px 0 38px 0;
        white-space: pre-wrap; word-break: break-word;
    }
    .b-byline {
        position: relative; z-index: 1; font-size: 44px; color: #b08a3e;
        font-weight: 600; margin-bottom: 14px; word-break: break-word;
    }
    .b-byline .b-who { font-weight: 700; }
    .b-time {
        position: relative; z-index: 1; font-size: 33px; color: #a89f8a;
        margin-bottom: 50px; letter-spacing: 1px;
    }
    .b-card .mag-cmt { position: relative; z-index: 1; }

    /* ============ C3 单人合集（引号编辑风 · 右上头像） ============ */
    .c3-head {
        display: flex; justify-content: space-between; align-items: center;
        padding: 60px 98px; border-bottom: 3px solid #e3ddcd;
    }
    .c3-head-info { min-width: 0; }
    .c3-title {
        font-size: 80px; font-weight: 700; color: #b08a3e; margin-top: 16px;
        line-height: 1.1; word-break: break-word;
    }
    .c3-head-av { width: 180px; height: 180px; }
    .c3-item { padding: 54px 98px; border-bottom: 2px solid #ece6d7; }
    .c3-item:last-of-type { border-bottom: none; }
    .c3-qline { display: flex; gap: 36px; align-items: flex-start; }
    .c3-qm {
        font-family: Georgia, 'Times New Roman', serif; font-size: 120px;
        color: #dcd0b2; line-height: 0.78; flex-shrink: 0;
    }
    .c3-col { flex: 1; min-width: 0; }
    .c3-qt {
        font-size: 64px; line-height: 1.5; color: #24211c;
        white-space: pre-wrap; word-break: break-word;
    }
    .c3-meta {
        font-size: 31px; color: #a89f8a; margin-top: 18px; letter-spacing: 1px;
    }

    /* ============ M3 多人合集（左头像名录） ============ */
    .m3-head {
        padding: 76px 98px 50px 98px; border-bottom: 3px solid #e3ddcd;
    }
    .m3-title {
        font-size: 84px; font-weight: 700; color: #1c1a17; margin-top: 14px;
        line-height: 1.15; word-break: break-word;
    }
    .m3-item {
        display: flex; gap: 44px; padding: 56px 98px;
        border-bottom: 2px solid #ece6d7; align-items: flex-start;
    }
    .m3-item:last-of-type { border-bottom: none; }
    .m3-av { width: 164px; height: 164px; }
    .m3-bd { flex: 1; min-width: 0; }
    .m3-top {
        display: flex; align-items: baseline; justify-content: space-between;
        gap: 24px;
    }
    .m3-nm {
        font-size: 48px; font-weight: 700; color: #b08a3e; word-break: break-word;
    }
    .m3-num {
        font-family: Georgia, 'Times New Roman', serif; font-size: 64px;
        font-weight: 700; color: #dacfb3; line-height: 1; flex-shrink: 0;
    }
    .m3-qt {
        font-size: 58px; line-height: 1.5; color: #24211c; margin-top: 14px;
        white-space: pre-wrap; word-break: break-word;
    }
    .m3-meta {
        font-size: 31px; color: #a89f8a; margin-top: 16px; letter-spacing: 1px;
    }
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

            # 可选：等待指定 Web 字体加载完成再截图（仅在 options 指定时启用，
            # 默认渲染路径保持“不等字体”的高速行为不变）。
            wait_font_family = options.get("wait_font_family")
            if wait_font_family:
                try:
                    await page.evaluate(
                        """
                        async (cfg) => {
                            const family = cfg.family;
                            const selector = cfg.selector;
                            const timeout = cfg.timeout || 7000;
                            const el = selector
                                ? document.querySelector(selector)
                                : document.body;
                            const text = el ? (el.textContent || '') : '';
                            const spec = `100px '${family}'`;
                            const deadline = Date.now() + timeout;
                            while (Date.now() < deadline) {
                                try { await document.fonts.load(spec, text); } catch (e) {}
                                if (document.fonts.check(spec, text)) return true;
                                await new Promise(r => setTimeout(r, 120));
                            }
                            return false;
                        }
                        """,
                        {
                            "family": wait_font_family,
                            "selector": options.get("wait_font_selector"),
                            "timeout": int(options.get("wait_font_timeout", 7000)),
                        },
                    )
                except Exception:
                    # 字体加载失败时静默降级，使用回退字体继续渲染
                    pass

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
                f'<b>Bot ·</b> {html.escape(c.text)}'
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
        """单条语录：B 版 — 右上头像 · 大字编辑风。"""
        avatar_b64 = await QuoteRenderer._fetch_avatar_b64(q.qq)

        safe_text = html.escape(q.text)
        safe_name = html.escape(q.name)
        time_text = QuoteRenderer._get_time_text(q.created_at)
        count_text = f"#{index} / {total}" if total > 0 else "AstrBot"

        src_html = QuoteRenderer._magazine_source_html(q, current_group_id)
        cmt_html = QuoteRenderer._build_magazine_comments(q, bot_qq, bot_name)
        plugin_info_text = "Menkelo/astrbot_plugin_quote_core"

        html_content = f"""
        <html>
        <head>
            <meta charset="utf-8">
            <link rel="preconnect" href="https://cdn.jsdelivr.net" crossorigin>
            <link rel="stylesheet"
                  href="https://cdn.jsdelivr.net/npm/@fontsource/noto-serif-sc@5.2.9/index.css">
            <style>
                {MAGAZINE_CSS}
                body {{ width: 1600px; }}
                /* 单条语录：本文用思源宋体（衬线/宋体），系统宋体兜底 */
                .b-card .b-qtext,
                .b-card .b-byline {{
                    font-family: 'Noto Serif SC', 'Source Han Serif SC',
                                 'Songti SC', SimSun, STSong, 'Noto Serif',
                                 Georgia, 'Times New Roman', serif;
                }}
            </style>
        </head>
        <body>
            <div class="mag">
                <div class="b-card">
                    <span class="b-wm">&ldquo;</span>
                    <div class="b-top">
                        <div class="b-top-left">
                            <div class="mag-kicker">QUOTE</div>
                            <span class="b-idx">{count_text}</span>
                        </div>
                        <img class="mag-av b-av" src="{avatar_b64}">
                    </div>
                    <div class="b-qtext">{safe_text}</div>
                    <div class="b-byline">—— <span class="b-who">{safe_name}</span>{src_html}</div>
                    <div class="b-time">{time_text}</div>
                    {cmt_html}
                </div>
                <div class="mag-footer">
                    <span class="fp">{plugin_info_text}</span>
                </div>
            </div>
        </body>
        </html>
        """

        return html_content, {
            "full_page": True,
            "viewport": {"width": 1600, "height": 1},
            # 仅单条卡片等待宋体加载完成再截图，确保字体生效
            "wait_font_family": "Noto Serif SC",
            "wait_font_selector": ".b-qtext",
            "wait_font_timeout": 7000,
        }

    @staticmethod
    async def _render_collection_magazine(
        quotes: List[Quote],
        title: str,
        self_qq: str,
        current_group_id: Optional[str] = None,
        bot_name: str = "AI鉴赏家",
    ) -> Tuple[str, Dict[str, Any]]:
        """单人语录合集：C3 — 引号编辑风 · 右上头像。标题仅名字。"""
        avatar_b64 = await QuoteRenderer._fetch_avatar_b64(self_qq)

        items_html = ""
        for i, q in enumerate(quotes):
            safe_text = html.escape(q.text)
            time_text = QuoteRenderer._get_time_text(q.created_at)
            src_html = QuoteRenderer._magazine_source_html(q, current_group_id)
            cmt_html = QuoteRenderer._build_magazine_comments(
                q, self_qq, bot_name
            )
            items_html += f"""
            <div class="c3-item">
                <div class="c3-qline">
                    <span class="c3-qm">&ldquo;</span>
                    <div class="c3-col">
                        <div class="c3-qt">{safe_text}</div>
                        {cmt_html}
                        <div class="c3-meta">{time_text}{src_html}</div>
                    </div>
                </div>
            </div>
            """

        # 标题仅保留名字（去掉 "的随机语录"）
        suffix = "的随机语录"
        name_only = title.rsplit(suffix, 1)[0] if suffix in title else title
        title_html = html.escape(name_only)

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
                <div class="c3-head">
                    <div class="c3-head-info">
                        <div class="mag-kicker">QUOTE COLLECTION</div>
                        <div class="c3-title">{title_html}</div>
                    </div>
                    <img class="mag-av c3-head-av" src="{avatar_b64}">
                </div>
                {items_html}
                <div class="mag-footer">
                    <span class="fp">{plugin_info_text}</span>
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
        """多人随机语录合集：M3 — 左头像名录。"""
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
            <div class="m3-item">
                <img class="mag-av m3-av" src="{ava}">
                <div class="m3-bd">
                    <div class="m3-top">
                        <span class="m3-nm">{safe_name}</span>
                        <span class="m3-num">{i + 1:02d}</span>
                    </div>
                    <div class="m3-qt">{safe_text}</div>
                    <div class="m3-meta">{time_text}{src_html}</div>
                    {cmt_html}
                </div>
            </div>
            """

        title_html = html.escape(title)
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
                <div class="m3-head">
                    <div class="mag-kicker">QUOTE COLLECTION</div>
                    <div class="m3-title">{title_html}</div>
                </div>
                {items_html}
                <div class="mag-footer">
                    <span class="fp">{plugin_info_text}</span>
                </div>
            </div>
        </body>
        </html>
        """

        return html_content, {
            "full_page": True,
            "viewport": {"width": 1600, "height": 1},
        }
