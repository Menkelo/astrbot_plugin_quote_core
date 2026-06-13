from __future__ import annotations

import asyncio
import time
import secrets
import random
import re
import json
import os
import base64
from pathlib import Path
from typing import Dict, List, Optional, Set

from astrbot.api import logger
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, StarTools
import astrbot.api.message_components as Comp

from astrbot.core.star.filter.command import CommandFilter
from astrbot.core.star.filter.command_group import CommandGroupFilter
from astrbot.core.star.star_handler import star_handlers_registry, StarHandlerMetadata

from .model import Quote, Comment
from .dao import QuoteStore
from .renderer import QuoteRenderer
from .service import OneBotService
from .llm_client import LLMClient
from .utils import extract_plaintext

PLUGIN_NAME = "astrbot_plugin_quote_core"

MANUAL_COMMENT_SYSTEM_PROMPT = """
你是一个群聊乐子锐评员，专门给被手动收录的语录写一句评论。

目标不是温柔鉴赏，而是精准抓乐子：要抽象、要有网感、要像群友看完之后绷不住的短评。

写法要求：
- 只输出一句中文点评，尽量控制在 30 字左右，最多不要超过 40 字。
- 必须具体贴着原句讲，抓住最离谱、最怪、最反差、最像神人发言的地方。
- 语气可以锐利、阴阳、缺德一点，但不要辱骂现实身份、不要人身攻击、不要扩写成小作文。
- 少用“这句话太逆天了”“反差感爆棚”这种模板废话。
- 不要复述原句，不要解释任务，不要 Markdown，不要 JSON。

风格参考：
- 这不是表白，这是把精神状态按在公屏上裸奔。
- 逻辑刚起步就拐进了无人区，还一脚油门没松。
- 看似在聊天，实则在给群友展示脑回路违建。
- 这句的抽象程度已经不是发言，是精神污染采样。
""".strip()


class QuotesPlugin(Star):
    def __init__(self, context: Context, config: Dict = None):
        super().__init__(context)
        self.config = config or {}

        self.data_dir = Path(StarTools.get_data_dir(PLUGIN_NAME))
        self.store = QuoteStore(self.data_dir)

        curr_dir = Path(__file__).parent
        QuoteRenderer.init_resources(curr_dir)

        self._wake_prefixes: List[str] = self._load_wake_prefixes()
        self._all_commands: Set[str] = self._load_all_commands()

        self._last_sent_qid: Dict[str, str] = {}
        self._processed_msg_ids: Dict[str, float] = {}

        self.regex_routes = [
            (re.compile(r"^收录(\s|$)"), self._logic_add),
            (re.compile(r"^语录([\s\d].*)?$"), self._logic_random),
            (re.compile(r"^删除(\s|$)"), self._logic_delete),
        ]

    async def terminate(self):
        await QuoteRenderer.shutdown()

    # ================= 基础工具 =================

    def _find_cmd_config(self) -> Optional[Path]:
        env_path = os.getenv("ASTROBOT_CMD_CONFIG")
        if env_path and Path(env_path).exists():
            return Path(env_path)

        for parent in Path(__file__).resolve().parents:
            candidate = parent / "data" / "cmd_config.json"
            if candidate.exists():
                return candidate

        return None

    def _load_wake_prefixes(self) -> List[str]:
        prefixes = []
        cfg_path = self._find_cmd_config()
        if not cfg_path or not cfg_path.exists():
            return []

        try:
            raw = cfg_path.read_text(encoding="utf-8-sig")
            try:
                data = json.loads(raw)
            except Exception:
                cleaned = re.sub(r"/\*.*?\*/|//.*?$", "", raw, flags=re.S | re.M)
                data = json.loads(cleaned)

            if not isinstance(data, dict):
                return []

            wp = None
            for k, v in data.items():
                if str(k).lower() in ("wake_prefix", "wake_prefixes", "prefix"):
                    wp = v
                    break

            if isinstance(wp, str):
                prefixes.append(wp.strip())
            elif isinstance(wp, list):
                prefixes.extend([str(x).strip() for x in wp if str(x).strip()])
        except Exception:
            pass

        seen = set()
        out = []
        for p in prefixes:
            if p and p not in seen:
                out.append(p)
                seen.add(p)
        return out

    def _strip_wake_prefix(self, text: str) -> str:
        t = text.strip()
        for p in self._wake_prefixes:
            if p and t.startswith(p):
                t = t[len(p):].lstrip()
                break
        return t

    def _has_wake_prefix(self, text: str) -> bool:
        t = text.strip()
        return any(p and t.startswith(p) for p in self._wake_prefixes)

    def _extract_aliases(self, filter_obj) -> Set[str]:
        aliases = set()
        for attr in ("alias", "aliases", "alias_set"):
            val = getattr(filter_obj, attr, None)
            if val:
                if isinstance(val, dict):
                    aliases.update(val.keys())
                elif isinstance(val, (list, set, tuple)):
                    aliases.update(val)
                else:
                    aliases.add(str(val))
        return {str(x).strip() for x in aliases if str(x).strip()}

    def _load_all_commands(self) -> Set[str]:
        commands = set()
        try:
            all_stars_metadata = self.context.get_all_stars()
            active_modules = {
                star.module_path
                for star in all_stars_metadata
                if getattr(star, "activated", True)
            }
        except Exception:
            active_modules = None

        for handler in star_handlers_registry:
            if not isinstance(handler, StarHandlerMetadata):
                continue
            if active_modules and handler.handler_module_path not in active_modules:
                continue

            for f in handler.event_filters:
                if isinstance(f, CommandFilter):
                    if f.command_name:
                        commands.add(str(f.command_name))
                    commands.update(self._extract_aliases(f))
                elif isinstance(f, CommandGroupFilter):
                    if f.group_name:
                        commands.add(str(f.group_name))
                    commands.update(self._extract_aliases(f))

        return {c for c in commands if c}

    def _starts_with_command(self, text: str) -> bool:
        if not text:
            return False
        if not self._all_commands:
            self._all_commands = self._load_all_commands()

        t = text.strip()
        for cmd in self._all_commands:
            if not cmd:
                continue
            if t == cmd:
                return True
            if t.startswith(cmd):
                if len(t) == len(cmd):
                    return True
                nxt = t[len(cmd)]
                if nxt.isspace() or nxt.isdigit() or nxt in "@#":
                    return True
        return False

    def _is_command_text(self, text: str) -> bool:
        raw = text.strip()
        if self._has_wake_prefix(raw):
            stripped = self._strip_wake_prefix(raw)
            return self._starts_with_command(stripped)
        if self.config.get("ignore_prefix", False):
            return self._starts_with_command(raw)
        return False

    def _check_consumed(self, event: AstrMessageEvent) -> bool:
        try:
            msg_id = str(
                getattr(event.message_obj, "message_id", "")
                or getattr(event.raw_event, "message_id", "")
            )
            if not msg_id:
                msg_id = (
                    f"content_hash_{hash(event.message_str)}_"
                    f"{event.get_sender_id()}_{int(time.time())}"
                )
        except Exception:
            return False

        now = time.time()
        keys_to_remove = [
            k for k, v in self._processed_msg_ids.items()
            if now - v > 5.0
        ]
        for k in keys_to_remove:
            self._processed_msg_ids.pop(k, None)

        if msg_id in self._processed_msg_ids:
            return True

        self._processed_msg_ids[msg_id] = now
        return False

    def _is_blocked(self, text: str) -> bool:
        if not text:
            return True
        if self._is_command_text(text):
            return True
        return False

    async def _generate_ai_comment(self, event: AstrMessageEvent, quote_text: str) -> Optional[str]:
        if not self.config.get("manual_ai_comment_enabled", False):
            return None

        provider = await self._resolve_provider(event)
        if not provider:
            return None

        user_prompt = (
            f"语录原文：{quote_text}\n\n"
            "给这句话写一句乐子锐评。"
        )

        try:
            resp = await provider.text_chat(
                prompt=user_prompt,
                system_prompt=MANUAL_COMMENT_SYSTEM_PROMPT,
                session_id=None,
            )
            text = getattr(resp, "completion_text", None) or getattr(resp, "text", None)
            return str(text).strip().strip('"“”')[:60] if text else None
        except Exception as e:
            logger.warning(f"[QuoteCore] 手动收录 AI 点评生成失败: {e}")
            return None

    async def _generate_and_save_ai_comment(
        self,
        event: AstrMessageEvent,
        service: OneBotService,
        qid: str,
        group_id: str,
        quote_text: str,
    ):
        try:
            ai_comment = await self._generate_ai_comment(event, quote_text)
            if not ai_comment:
                return

            bot_qq = self._get_self_id(event) or "10000"
            bot_name = await service.get_user_name(group_id, bot_qq) or "AI鉴赏家"
            await self.store.add_comment(
                qid,
                Comment(
                    qq=bot_qq,
                    name=bot_name,
                    text=ai_comment,
                    created_at=time.time(),
                )
            )
        except Exception as e:
            logger.warning(f"[QuoteCore] 后台手动收录 AI 点评保存失败: {e}")

    async def _resolve_provider(self, event: AstrMessageEvent):
        class _CfgAdapter:
            def __init__(self, cfg):
                self._cfg = cfg or {}

            def get_llm_provider_id(self):
                return self._cfg.get("llm_provider_id")

        umo = getattr(event, "unified_msg_origin", None)
        provider_id = await LLMClient.get_provider_id_with_fallback(
            self.context,
            _CfgAdapter(self.config),
            "llm_provider_id",
            umo,
        )

        if not provider_id:
            return None

        try:
            return self.context.get_provider_by_id(provider_id=provider_id)
        except Exception:
            try:
                return self.context.get_provider_by_id(provider_id)
            except Exception:
                return None

    def _image_result_from_bytes(self, event: AstrMessageEvent, img_bytes: bytes):
        b64 = base64.b64encode(img_bytes).decode("ascii")
        return event.chain_result([Comp.Image(file=f"base64://{b64}")])

    # ================= 指令注册 =================

    @filter.command("收录", desc="回复某条消息，将其收录到语录库中")
    async def cmd_add(self, event: AstrMessageEvent):
        async for res in self._logic_add(event):
            yield res

    @filter.command("语录", desc="随机抽取语录。支持：/语录、/语录 5、/语录 @某人")
    async def cmd_random(self, event: AstrMessageEvent):
        async for res in self._logic_random(event):
            yield res

    @filter.command("删除", desc="回复删除Bot发送的语录")
    async def cmd_delete(self, event: AstrMessageEvent):
        async for res in self._logic_delete(event):
            yield res

    # ================= 辅助监听 =================

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def _handle_aux_events(self, event: AstrMessageEvent):
        """
        辅助监听：
        - 戳一戳优先处理
        - 文本无前缀触发仍按 ignore_prefix 控制
        """
        is_poke = self._event_has_poke(event)

        if is_poke:
            async for res in self._logic_poke(event):
                yield res
            return

        self_id = self._get_self_id(event)
        if event.get_sender_id() == self_id:
            return

        if not self.config.get("ignore_prefix", False):
            return

        raw_text = "".join([
            s.text
            for s in event.message_obj.message
            if isinstance(s, Comp.Plain)
        ]).strip()

        if not raw_text:
            return

        if self._has_wake_prefix(raw_text):
            return

        for pattern, logic_func in self.regex_routes:
            if pattern.match(raw_text):
                async for res in logic_func(event):
                    yield res

    # ================= 业务逻辑 =================

    async def _logic_add(self, event: AstrMessageEvent):
        if self._check_consumed(event):
            return

        if event.get_platform_name() != "aiocqhttp":
            yield event.plain_result("⚠️ 仅支持 OneBot 协议")
            return

        reply_id = None
        for seg in event.get_messages():
            if isinstance(seg, Comp.Reply):
                reply_id = str(
                    getattr(seg, "id", None)
                    or getattr(seg, "msgId", None)
                )

        if not reply_id:
            yield event.plain_result("请回复某条消息发送 /收录")
            return

        service = OneBotService(event.bot)
        msg_data = await service.get_msg(reply_id)

        text = extract_plaintext(msg_data.get("message"))
        sender = msg_data.get("sender") or {}

        if not text or not sender:
            yield event.plain_result("收录失败：内容为空或无法获取发送者")
            return

        if self._is_blocked(text):
            yield event.plain_result("⚠️ 该消息为命令消息，无法收录")
            return

        target_qq = str(sender.get("user_id") or "")
        group_id = self._get_real_group_id(event) or str(event.get_group_id())
        name = await service.get_user_name(group_id, target_qq)

        self_id = self._get_self_id(event)
        if target_qq == self_id:
            yield event.plain_result("⚠️ 不可以收录机器人哦")
            return

        blacklist = [str(x) for x in self.config.get("user_blacklist", [])]
        if target_qq in blacklist:
            yield event.plain_result("⚠️ 该用户在黑名单中，无法收录")
            return

        if re.search(r"(https?:\/\/|www\.)", text, re.IGNORECASE):
            yield event.plain_result("⚠️ 包含链接，不支持收录")
            return

        if self.store.check_exists(group_id, text):
            yield event.plain_result("⚠️ 语录已存在")
            return

        qid = secrets.token_hex(4)
        quote = Quote(
            id=qid,
            qq=target_qq,
            name=name,
            text=text,
            created_by=event.get_sender_id(),
            created_at=float(msg_data.get("time") or time.time()),
            group=group_id,
        )

        ok = await self.store.add_quote(quote)
        if not ok:
            yield event.plain_result("⚠️ 语录已存在")
            return

        yield event.plain_result(f"已收录 {name} 的语录")

        if self.config.get("manual_ai_comment_enabled", False):
            asyncio.create_task(
                self._generate_and_save_ai_comment(
                    event,
                    service,
                    qid,
                    group_id,
                    text,
                )
            )

    async def _logic_random(self, event: AstrMessageEvent):
        if self._check_consumed(event):
            return

        group_id = self._get_real_group_id(event) or str(event.get_group_id())
        is_global = self.config.get("global_mode", False)
        search_group = None if is_global else group_id

        target_qq = None
        count = 1

        for seg in event.message_obj.message:
            if isinstance(seg, Comp.At):
                target_qq = str(seg.qq)
                break

        if not target_qq and "自己" in event.message_str:
            target_qq = str(event.get_sender_id())

        plain_text_only = "".join([
            s.text
            for s in event.message_obj.message
            if isinstance(s, Comp.Plain)
        ])

        nums = re.findall(r"\d+", plain_text_only)
        if nums:
            count = min(int(nums[0]), self.config.get("max_batch_count", 10))

        service = OneBotService(event.bot)

        bot_qq = self._get_self_id(event) or "10000"
        bot_name = "Bot"

        if not target_qq and count > 1:
            quotes = self.store.get_random_batch(search_group, count)
            if not quotes:
                yield event.plain_result("该群组暂无语录")
                return

            names = await asyncio.gather(*[
                service.get_user_name(group_id, q.qq)
                for q in quotes
            ])
            for q, name in zip(quotes, names):
                q.name = name

            if is_global:
                group_names = await asyncio.gather(*[
                    service.get_group_name(q.group)
                    for q in quotes
                ])
                for q, gn in zip(quotes, group_names):
                    setattr(q, "temp_source_label", gn)

            html_content, opts = await QuoteRenderer.render_merged_card(
                quotes,
                "随机语录抽卡",
                bot_qq,
                title_is_blue=False,
                current_group_id=group_id,
                bot_name=bot_name,
            )

            img_bytes = await QuoteRenderer.html_to_png_bytes(html_content, opts)
            yield self._image_result_from_bytes(event, img_bytes)
            return

        if target_qq and count > 1:
            quotes = self.store.get_user_quotes(search_group, target_qq)
            if not quotes:
                yield event.plain_result("该用户暂无语录")
                return

            sel = random.sample(quotes, min(len(quotes), count))
            name = await service.get_user_name(group_id, target_qq)

            for q in sel:
                q.name = name

            html_content, opts = await QuoteRenderer.render_merged_card(
                sel,
                f"{name}的随机语录",
                target_qq,
                title_is_blue=True,
                current_group_id=group_id,
                bot_name=bot_name,
            )

            img_bytes = await QuoteRenderer.html_to_png_bytes(html_content, opts)
            yield self._image_result_from_bytes(event, img_bytes)
            return

        quote = self.store.get_random(search_group, target_qq)
        if not quote:
            msg = "该用户暂无语录" if target_qq else "该群组暂无语录"
            yield event.plain_result(msg)
            return

        self._last_sent_qid[group_id] = quote.id
        if is_global:
            quote.name, gn = await asyncio.gather(
                service.get_user_name(group_id, quote.qq),
                service.get_group_name(quote.group),
            )
            setattr(quote, "temp_source_label", gn)
        else:
            quote.name = await service.get_user_name(group_id, quote.qq)

        all_data = self.store.get_raw_data()
        subset = [
            q for q in all_data
            if (str(q.get("group")) == group_id or is_global)
            and str(q.get("qq")) == str(quote.qq)
        ]

        idx = next(
            (i + 1 for i, q in enumerate(subset) if q.get("id") == quote.id),
            0,
        )

        html_content, opts = await QuoteRenderer.render_single_card(
            quote,
            idx,
            len(subset),
            current_group_id=group_id,
            bot_qq=bot_qq,
            bot_name=bot_name,
        )

        img_bytes = await QuoteRenderer.html_to_png_bytes(html_content, opts)
        yield self._image_result_from_bytes(event, img_bytes)

    async def _logic_delete(self, event: AstrMessageEvent):
        if self._check_consumed(event):
            return

        if self.config.get("admin_only", False) and not event.is_admin():
            yield event.plain_result("仅Bot管理员可删除")
            return

        gid = self._get_real_group_id(event) or str(event.get_group_id())
        qid = self._last_sent_qid.get(gid)

        if not qid:
            yield event.plain_result("无上一条语录")
            return

        if await self.store.delete_quote(qid):
            yield event.plain_result("删除成功")
            self._last_sent_qid.pop(gid, None)
        else:
            yield event.plain_result("删除失败")

    async def _logic_poke(self, event: AstrMessageEvent):
        """
        戳一戳触发语录。

        当前逻辑：
        - poke_enabled=false：关闭
        - poke_enabled=true：开启
        - 戳机器人：随机发送一条语录
        - 戳群友：发送该群友的语录
        - 没有可发送语录时静默

        兼容旧配置：
        - 如果没有 poke_enabled，则 poke_mode=关闭 表示关闭
        - poke_mode 其他值视为开启
        """
        if not self._is_poke_enabled():
            logger.info("[QuoteCore] 戳一戳语录开关已关闭，忽略")
            return

        if self._check_consumed(event):
            logger.info("[QuoteCore] 戳一戳事件被去重消费，忽略")
            return

        target_qq = self._get_poke_target_id(event)
        group_id = self._get_real_group_id(event)
        bot_qq = self._get_self_id(event) or "10000"

        logger.info(
            f"[QuoteCore] 戳一戳解析结果: "
            f"enabled={self._is_poke_enabled()}, "
            f"target_qq={target_qq}, group_id={group_id}, "
            f"sender={event.get_sender_id()}, self_id={bot_qq}"
        )

        if not target_qq:
            logger.warning("[QuoteCore] 无法解析戳一戳目标 target_qq，已忽略")
            return

        if not group_id:
            logger.warning("[QuoteCore] 无法解析戳一戳群号 group_id，已忽略")
            return

        is_global = self.config.get("global_mode", False)
        search_group = None if is_global else group_id

        service = OneBotService(event.bot)

        quote_target = None if str(target_qq) == str(bot_qq) else target_qq
        quote = self.store.get_random(search_group, quote_target)

        if not quote:
            logger.info(
                f"[QuoteCore] 戳一戳没有可发送语录，静默: "
                f"target_qq={target_qq}, quote_target={quote_target}, "
                f"group_id={group_id}, global={is_global}"
            )
            return

        self._last_sent_qid[group_id] = quote.id
        bot_name = "Bot"

        if is_global:
            quote.name, gn = await asyncio.gather(
                service.get_user_name(group_id, quote.qq),
                service.get_group_name(quote.group),
            )
            setattr(quote, "temp_source_label", gn)
        else:
            quote.name = await service.get_user_name(group_id, quote.qq)

        all_data = self.store.get_raw_data()
        subset = [
            q for q in all_data
            if (str(q.get("group")) == group_id or is_global)
            and str(q.get("qq")) == str(quote.qq)
        ]

        idx = next(
            (i + 1 for i, q in enumerate(subset) if q.get("id") == quote.id),
            0,
        )

        html_content, opts = await QuoteRenderer.render_single_card(
            quote,
            idx,
            len(subset),
            current_group_id=group_id,
            bot_qq=bot_qq,
            bot_name=bot_name,
        )

        img_bytes = await QuoteRenderer.html_to_png_bytes(html_content, opts)
        yield self._image_result_from_bytes(event, img_bytes)

    # ================= OneBot / AstrBot 兼容辅助 =================

    def _is_poke_enabled(self) -> bool:
        """
        戳一戳语录开关。

        推荐新配置：
            poke_enabled: true / false

        兼容旧配置：
            poke_mode = 关闭 / 仅戳Bot / 任意戳

        当前含义：
        - 开启：戳机器人随机语录；戳群友发送该群友语录
        - 关闭：不响应
        """
        if "poke_enabled" in self.config:
            return bool(self.config.get("poke_enabled", False))

        mode = self.config.get("poke_mode", "关闭")
        return mode != "关闭"

    def _is_poke_segment(self, seg) -> bool:
        try:
            if isinstance(seg, Comp.Poke):
                return True
        except Exception:
            pass

        try:
            cls_name = seg.__class__.__name__.lower()
            if "poke" in cls_name:
                return True
        except Exception:
            pass

        try:
            seg_type = getattr(seg, "type", None)
            if seg_type is not None and "poke" in str(seg_type).lower():
                return True
        except Exception:
            pass

        try:
            seg_type = getattr(seg, "component_type", None)
            if seg_type is not None and "poke" in str(seg_type).lower():
                return True
        except Exception:
            pass

        return False

    def _event_has_poke(self, event) -> bool:
        try:
            for seg in event.message_obj.message:
                if self._is_poke_segment(seg):
                    return True
        except Exception:
            pass

        raw = getattr(event, "raw_event", None)

        try:
            if isinstance(raw, dict):
                if str(raw.get("sub_type", "")).lower() == "poke":
                    return True

                if (
                    str(raw.get("notice_type", "")).lower() in ("notify", "poke")
                    and (
                        raw.get("target_id")
                        or raw.get("target")
                        or raw.get("id")
                    )
                ):
                    return True
        except Exception:
            pass

        try:
            if "poke" in str(raw).lower():
                return True
        except Exception:
            pass

        return False

    def _normalize_poke_id_value(self, value) -> Optional[str]:
        """
        规范化戳一戳目标 ID。

        AstrBot 的 Poke.target_id 可能是方法，需要调用。
        同时过滤 None / 空字符串 / 0 / "0"。
        """
        if value is None:
            return None

        try:
            if callable(value):
                value = value()
        except Exception:
            return None

        if value is None:
            return None

        value = str(value).strip()

        if not value:
            return None
        if value == "0":
            return None
        if value.lower() == "none":
            return None
        if value.startswith("<bound method"):
            return None

        return value

    def _get_raw_value(self, event, *keys):
        raw = getattr(event, "raw_event", None)

        candidates = []

        def add_candidate(obj):
            try:
                if obj is not None and obj not in candidates:
                    candidates.append(obj)
            except Exception:
                pass

        add_candidate(raw)
        add_candidate(getattr(event, "message_obj", None))

        for base in list(candidates):
            for attr in ("raw_event", "data", "event", "message_obj", "raw"):
                try:
                    add_candidate(getattr(base, attr, None))
                except Exception:
                    pass

            try:
                d = getattr(base, "__dict__", None)
                if isinstance(d, dict):
                    add_candidate(d)
            except Exception:
                pass

            try:
                if hasattr(base, "model_dump"):
                    add_candidate(base.model_dump())
            except Exception:
                pass

            try:
                if hasattr(base, "dict"):
                    add_candidate(base.dict())
            except Exception:
                pass

        for obj in candidates:
            if obj is None:
                continue

            if isinstance(obj, dict):
                for k in keys:
                    if k in obj and obj.get(k) is not None:
                        return obj.get(k)

                for nested_key in ("data", "raw_event", "event", "notice"):
                    nested = obj.get(nested_key)
                    if isinstance(nested, dict):
                        for k in keys:
                            if k in nested and nested.get(k) is not None:
                                return nested.get(k)

            try:
                for k in keys:
                    val = obj.get(k)
                    if val is not None:
                        return val
            except Exception:
                pass

            for k in keys:
                try:
                    val = getattr(obj, k, None)
                    if val is not None:
                        return val
                except Exception:
                    pass

        return None

    def _get_poke_target_id(self, event) -> Optional[str]:
        """
        获取戳一戳目标 QQ。

        兼容你的日志：
            Poke dict={'id': 1491571511, 'qq': 0}

        优先级：
            target_id / target / target_qq / id / qq / uin / user_id

        注意：
            target_id 可能是方法，需要调用。
        """
        target_qq = None

        try:
            for seg in event.message_obj.message:
                if self._is_poke_segment(seg):
                    try:
                        logger.info(
                            f"[QuoteCore] Poke Segment: "
                            f"class={seg.__class__}, "
                            f"dict={getattr(seg, '__dict__', None)}, "
                            f"str={seg}"
                        )
                    except Exception:
                        pass

                    candidate_attrs = [
                        "target_id",
                        "target",
                        "target_qq",
                        "id",
                        "qq",
                        "uin",
                        "user_id",
                    ]

                    for attr in candidate_attrs:
                        try:
                            val = getattr(seg, attr, None)
                            val = self._normalize_poke_id_value(val)
                            if val:
                                target_qq = val
                                break
                        except Exception:
                            continue

                    if target_qq:
                        break

        except Exception as e:
            logger.warning(f"[QuoteCore] 从 Poke Segment 解析 target_qq 失败: {e}")

        if not target_qq:
            raw_val = self._get_raw_value(
                event,
                "target_id",
                "target",
                "target_qq",
                "id",
                "qq",
                "uin",
                "user_id",
            )
            target_qq = self._normalize_poke_id_value(raw_val)

        if not target_qq:
            return None

        return target_qq

    def _get_real_group_id(self, event) -> str:
        group_id = self._get_raw_value(
            event,
            "group_id",
            "group",
            "groupId",
            "group_id_str",
        )

        if group_id:
            return str(group_id)

        try:
            gid = event.get_group_id()
            if gid:
                return str(gid)
        except Exception:
            pass

        return ""

    def _get_self_id(self, event) -> Optional[str]:
        try:
            if hasattr(event.message_obj, "self_id"):
                sid = getattr(event.message_obj, "self_id", None)
                if sid:
                    return str(sid)
        except Exception:
            pass

        sid = self._get_raw_value(event, "self_id", "bot_id")

        if sid:
            return str(sid)

        return None
