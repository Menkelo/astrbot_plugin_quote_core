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


# --- 轻量版 CSS（宽度 1600px，缩放比例≈0.72） ---
MOMENTS_CSS = """
    /* 已禁用 Google Fonts 远程字体，避免 Playwright 截图时等待字体加载超时 */
    
    :root {
        --bg-color: #0d0d0d;
        --text-primary: #f2f2f2;
        --text-secondary: #888888;
        --name-color: #8fbdf5;     
        --divider-color: #262626;
        --link-bg: #1a1a1a;
        --comment-bg: #161616;
    }

    * { box-sizing: border-box; margin: 0; padding: 0; }

    body {
        margin: 0; 
        font-family: 'Noto Sans SC', 'Microsoft YaHei', 'PingFang SC', 'Source Han Sans SC', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        background: var(--bg-color);
        color: var(--text-primary);
        -webkit-font-smoothing: antialiased;
        -moz-osx-font-smoothing: grayscale;
        overflow: hidden;
    }

    .moments-item {
        display: flex; flex-direction: row; align-items: flex-start;
        width: 100%;
        padding: 60px 70px;
        background: var(--bg-color);
    }
    
    .moments-item.simple {
        padding: 45px 70px; 
    }

    .moments-item.simple .avatar-col { display: none; } 

    .moments-item.simple .text-body { 
        font-size: 66px;
        margin-bottom: 24px; 
    }

    .moments-item.simple .content-col { padding-top: 0; }

    .avatar-col {
        margin-right: 40px;
        flex-shrink: 0;
    }

    .avatar { 
        width: 170px;
        height: 170px;
        border-radius: 22px; 
        object-fit: cover; 
        background: #222;
        border: 2px solid #333;
        box-shadow: 0 10px 30px rgba(0,0,0,0.5);
        image-rendering: -webkit-optimize-contrast;
    }

    .content-col {
        flex: 1;
        display: flex;
        flex-direction: column;
        min-width: 0;
        padding-top: 8px;
    }
    
    .nickname { 
        font-size: 60px;
        font-weight: 600;
        color: var(--name-color); 
        margin-bottom: 22px;
        line-height: 1.2;
        letter-spacing: 1px;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }
    
    .text-body { 
        font-size: 66px;
        color: var(--text-primary);
        line-height: 1.6; 
        margin-bottom: 36px; 
        word-wrap: break-word;
        white-space: pre-wrap; 
        text-align: justify;
        text-shadow: 0 2px 4px rgba(0,0,0,0.3);
    }

    .comments-section {
        margin-top: 28px;
        background: var(--comment-bg);
        border-radius: 10px;
        padding: 30px 45px;
        position: relative;
        border: 1px solid #2a2a2a;
    }

    .comments-section::before {
        content: '';
        position: absolute;
        top: -14px;
        left: 45px;
        border-width: 0 14px 14px 14px;
        border-style: solid;
        border-color: transparent transparent var(--comment-bg) transparent;
    }
    
    .comment-row {
        display: flex;
        align-items: flex-start;
        margin-bottom: 14px;
    }

    .comment-row:last-child {
        margin-bottom: 0;
    }
    
    .cmt-content { 
        flex: 1; 
        font-size: 36px; 
        line-height: 1.5;
        color: #ddd; 
        text-align: justify; 
        word-break: break-word;
    }

    .cmt-name { 
        color: var(--name-color); 
        font-weight: 600; 
        margin-right: 12px; 
    }
    
    .footer-row { 
        display: flex;
        align-items: flex-start;
        gap: 28px;
        margin-top: 8px;
        width: 100%;
    }

    .footer-left {
        display: grid;
        grid-template-columns: max-content minmax(0, 1fr);
        column-gap: 28px;
        align-items: start;
        flex: 1 1 auto;
        min-width: 0;
    }
    
    .time-text {
        font-size: 40px;
        color: var(--text-secondary);
        letter-spacing: 1px;
        white-space: nowrap;
    }
    
    .group-tag {
        font-size: 40px; 
        color: var(--name-color); 
        font-weight: 500;
        line-height: 1.35;
        min-width: 0;
        overflow-wrap: anywhere;
    }
    
    .index-tag {
        font-size: 34px;
        color: #666;
        font-weight: bold;
        background: #181818;
        padding: 8px 18px;
        border-radius: 10px;
        border: 2px solid #2a2a2a;
        flex: 0 0 auto;
        white-space: nowrap;
    }

    .list-container {
        width: 100%;
        display: flex;
        flex-direction: column;
    }
    
    .list-header {
        padding: 85px 70px 45px 70px;
        border-bottom: 2px solid var(--divider-color);
        background: #111;
        display: flex; 
        flex-direction: row; 
        align-items: center; 
    }
    
    .header-avatar-box {
        margin-right: 40px;
        flex-shrink: 0;
    }

    .header-avatar {
        width: 170px;
        height: 170px; 
        border-radius: 22px;
        object-fit: cover;
        background: #222;
        border: 2px solid #333;
        image-rendering: -webkit-optimize-contrast;
    }

    .header-left {
        display: flex;
        flex-direction: column;
        flex: 1;
        min-width: 0;
    }
    
    .header-title { 
        font-size: 68px; 
        font-weight: bold; 
        margin-bottom: 16px; 
        line-height: 1.1;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    .title-name {
        color: var(--name-color);
    }

    .title-white {
        color: #fff;
    }

    .header-sub {
        font-size: 36px;
        color: #666;
    }

    .card-footer {
        padding: 45px 70px 70px 70px;
        border-top: 2px solid var(--divider-color);
        background: #111;
        display: flex; 
        flex-direction: column; 
        align-items: flex-start;
    }
    
    .footer-plugin-info {
        font-size: 30px;
        color: #555;
        font-weight: bold;
        margin-bottom: 12px;
    }

    .footer-gen-time {
        font-size: 26px;
        color: #444;
        letter-spacing: 1px;
        font-weight: 500;
    }

    .divider {
        height: 2px;
        background: var(--divider-color);
        margin-left: 70px;
        margin-right: 70px;
    }
    
    .divider.normal {
        margin-left: 280px;
        margin-right: 0;
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
    async def render_single_card(
        q: Quote,
        index: int,
        total: int,
        current_group_id: Optional[str] = None,
        bot_qq: str = "10000",
        bot_name: str = "AI鉴赏家"
    ) -> Tuple[str, Dict[str, Any]]:
        avatar_b64 = await QuoteRenderer._fetch_avatar_b64(q.qq)

        safe_text = html.escape(q.text)
        safe_name = html.escape(q.name)

        time_text = QuoteRenderer._get_time_text(q.created_at)
        count_text = f"#{index} / {total}" if total > 0 else "AstrBot"
        group_html = QuoteRenderer._get_group_html(q, current_group_id)

        comments_html = await QuoteRenderer._prepare_comments_html(
            q,
            bot_qq,
            bot_name
        )

        gen_time = datetime.now().strftime("%Y-%m-%d %H:%M")
        plugin_info_text = "Menkelo/astrbot_plugin_quote_core"

        html_content = f"""
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                {MOMENTS_CSS}
                body {{
                    width: 1600px;
                    display: flex;
                    flex-direction: column;
                }}
            </style>
        </head>
        <body>
            <div class="moments-item" style="flex: 1;">
                <div class="avatar-col">
                    <img class="avatar" src="{avatar_b64}">
                </div>
                <div class="content-col">
                    <div class="nickname">{safe_name}</div>
                    <div class="text-body">{safe_text}</div>
                    <div class="footer-row">
                        <div class="footer-left">
                            <span class="time-text">{time_text}</span>
                            {group_html}
                        </div>
                        <span class="index-tag">{count_text}</span>
                    </div>
                    {comments_html}
                </div>
            </div>
            
            <div class="card-footer">
                <div class="footer-plugin-info">{plugin_info_text}</div>
                <div class="footer-gen-time">{gen_time}</div>
            </div>
        </body>
        </html>
        """

        return html_content, {
            "full_page": True,
            "viewport": {
                "width": 1600,
                "height": 1
            }
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

        header_avatar_html = ""

        if title_is_blue:
            header_avatar_b64 = await QuoteRenderer._fetch_avatar_b64(self_qq)
            header_avatar_html = f"""
            <div class="header-avatar-box">
                <img class="header-avatar" src="{header_avatar_b64}">
            </div>
            """

        avatar_map = {}

        if not title_is_blue:
            qq_set = {q.qq for q in quotes}

            tasks = [
                QuoteRenderer._fetch_avatar_b64(uid)
                for uid in qq_set
            ]
            results = await asyncio.gather(*tasks)

            avatar_map = {
                uid: b64
                for uid, b64 in zip(qq_set, results)
            }

        items_html = ""

        for i, q in enumerate(quotes):
            safe_text = html.escape(q.text)
            time_text = QuoteRenderer._get_time_text(q.created_at)

            group_html = QuoteRenderer._get_group_html(q, current_group_id)

            comments_html = await QuoteRenderer._prepare_comments_html(
                q,
                self_qq,
                bot_name
            )

            if title_is_blue:
                items_html += f"""
                <div class="moments-item simple">
                    <div class="content-col">
                        <div class="text-body">{safe_text}</div>
                        <div class="footer-row">
                            <div class="footer-left">
                                <span class="time-text">{time_text}</span>
                                {group_html}
                            </div>
                            <span class="index-tag">#{i + 1}</span>
                        </div>
                        {comments_html}
                    </div>
                </div>
                """

                divider_cls = "divider"

            else:
                ava = avatar_map.get(q.qq, QuoteRenderer.DEFAULT_AVATAR_B64)
                nickname_html = f'<div class="nickname">{html.escape(q.name)}</div>'

                items_html += f"""
                <div class="moments-item">
                    <div class="avatar-col">
                        <img class="avatar" src="{ava}">
                    </div>
                    <div class="content-col">
                        {nickname_html}
                        <div class="text-body">{safe_text}</div>
                        <div class="footer-row">
                            <div class="footer-left">
                                <span class="time-text">{time_text}</span>
                                {group_html}
                            </div>
                            <span class="index-tag">#{i + 1}</span>
                        </div>
                        {comments_html}
                    </div>
                </div>
                """

                divider_cls = "divider normal"

            if i < len(quotes) - 1:
                items_html += f'<div class="{divider_cls}"></div>'

        suffix = "的随机语录"

        if title_is_blue and suffix in title:
            name_part = title.rsplit(suffix, 1)[0]
            title_html = (
                f'<span class="title-name">{html.escape(name_part)}</span>'
                f'<span class="title-white">{suffix}</span>'
            )
        elif title_is_blue:
            title_html = f'<span class="title-name">{html.escape(title)}</span>'
        else:
            title_html = f'<span class="title-white">{html.escape(title)}</span>'

        sub_text = f"已随机抽取 {len(quotes)} 条语录"
        gen_time = datetime.now().strftime("%Y-%m-%d %H:%M")
        plugin_info_text = "Menkelo/astrbot_plugin_quote_core"

        html_content = f"""
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                {MOMENTS_CSS}
                body {{
                    width: 1600px;
                }}
            </style>
        </head>
        <body>
            <div class="list-container">
                <div class="list-header">
                    {header_avatar_html}
                    <div class="header-left">
                        <div class="header-title">{title_html}</div>
                        <div class="header-sub">{sub_text}</div>
                    </div>
                </div>
                
                {items_html}
                
                <div class="card-footer">
                    <div class="footer-plugin-info">{plugin_info_text}</div>
                    <div class="footer-gen-time">{gen_time}</div>
                </div>
            </div>
        </body>
        </html>
        """

        return html_content, {
            "full_page": True,
            "viewport": {
                "width": 1600,
                "height": 1
            }
        }
