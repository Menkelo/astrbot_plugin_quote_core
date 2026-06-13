import asyncio
import time
from typing import Dict, List, Optional
from .utils import is_valid_nickname

class OneBotService:
    _user_cache: Dict[str, tuple] = {}
    _group_cache_global: Dict[str, str] = {}
    _user_cache_ttl = 30 * 60

    def __init__(self, bot):
        self.bot = bot

    async def get_user_name(self, group_id: str, user_id: str) -> str:
        """获取用户昵称 (群名片 -> 陌生人 -> ID)"""
        if not user_id:
            return ""

        cache_key = f"{group_id}:{user_id}"
        cached = self._user_cache.get(cache_key)
        now = time.time()
        if cached and now - cached[0] < self._user_cache_ttl:
            return cached[1]
        
        # 1. 尝试获取群名片
        try:
            if group_id:
                ret = await self.bot.api.call_action(
                    "get_group_member_info",
                    group_id=int(group_id),
                    user_id=int(user_id),
                    no_cache=False
                )
                if ret:
                    raw = (ret.get("card") or ret.get("nickname") or "").strip()
                    if is_valid_nickname(raw):
                        self._user_cache[cache_key] = (now, raw)
                        return raw
        except:
            pass

        # 2. 尝试获取陌生人昵称
        try:
            ret = await self.bot.api.call_action(
                "get_stranger_info",
                user_id=int(user_id),
                no_cache=False
            )
            if ret:
                raw = (ret.get("nickname") or "").strip()
                if is_valid_nickname(raw):
                    self._user_cache[cache_key] = (now, raw)
                    return raw
        except:
            pass
        
        # 3. 兜底返回ID
        fallback = str(user_id)
        self._user_cache[cache_key] = (now, fallback)
        return fallback

    async def get_group_name(self, group_id: str) -> str:
        """获取群名称 (带缓存，仅返回群名，不包含群号)"""
        if not group_id:
            return ""
        if group_id in self._group_cache_global:
            return self._group_cache_global[group_id]
        
        try:
            ret = await self.bot.api.call_action("get_group_info", group_id=int(group_id), no_cache=False)
            name = (ret.get("group_name", "") if ret else "").strip()
            if name:
                # 仅展示群名，不带群号，保护隐私
                self._group_cache_global[group_id] = name
                return name
        except:
            pass
        
        # API 失败兜底：不泄露群号
        return "未知群聊"

    async def get_msg(self, message_id: str) -> Dict:
        """获取单条消息详情"""
        try:
            return await self.bot.api.call_action("get_msg", message_id=int(str(message_id))) or {}
        except:
            return {}

    async def fetch_history_robust(self, group_id: str, total_count: int) -> List[Dict]:
        """
        [NapCat适配] 鲁棒性拉取历史消息
        """
        collected = []
        cursor_seq = 0
        error_strike = 0
        # 估算循环次数，防止死循环
        max_loops = int(total_count / 50) + 10
        
        for _ in range(max_loops):
            if len(collected) >= total_count:
                break
            if error_strike > 10:
                break  # 熔断

            try:
                # NapCat/Go-CQHTTP 兼容参数
                payload = {
                    "group_id": int(group_id),
                    "count": 100,
                    "reverseOrder": True
                }
                if cursor_seq > 0:
                    payload["message_seq"] = cursor_seq
                
                res = await self.bot.api.call_action("get_group_msg_history", **payload)
                batch = res.get("messages", []) if res else []
                
                if not batch:
                    break  # 没有更多消息了
                
                # 更新游标
                oldest_msg = batch[0]
                cursor_seq = int(oldest_msg.get("message_seq") or oldest_msg.get("message_id") or 0)
                
                error_strike = 0
                collected.extend(batch)
                
                # 稍微休眠避免触发风控
                await asyncio.sleep(0.1)
                
            except Exception:
                error_strike += 1
                # 遇到错误尝试跳跃回溯
                jump_step = 50 * (2 ** (min(error_strike, 5) - 1))
                cursor_seq = max(0, cursor_seq - jump_step)
                await asyncio.sleep(0.2)

        # 结果去重并按时间排序
        unique_msgs = {str(m.get("message_id")): m for m in collected}.values()
        return sorted(unique_msgs, key=lambda x: x.get("time", 0))[-total_count:]
