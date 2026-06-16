import json
import random
import asyncio
import dataclasses
import os
import tempfile
from pathlib import Path
from typing import List, Optional, Dict, Any, Set
from astrbot.api import logger
from .model import Quote, Comment


class QuoteStore:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.file = self.data_dir / "quotes.json"
        self.group_dir = self.data_dir / "quotes_by_group"
        self._lock = asyncio.Lock()

        self._cache: List[Dict[str, Any]] = self._load()
        self._index: Set[str] = set()
        self._rebuild_index()

    def _load(self) -> List[Dict[str, Any]]:
        self.group_dir.mkdir(parents=True, exist_ok=True)

        group_files = sorted(self.group_dir.glob("*.json"))
        if group_files:
            return self._load_group_files(group_files)

        legacy_quotes = self._load_legacy_file()
        if legacy_quotes:
            self._save_all_group_files_sync(legacy_quotes)
            logger.info(
                f"[QuoteCore] 已将旧版 quotes.json 按群拆分到 {self.group_dir}"
            )
        return legacy_quotes

    def _load_legacy_file(self) -> List[Dict[str, Any]]:
        if not self.file.exists():
            return []
        try:
            data = json.loads(self.file.read_text(encoding="utf-8"))
            return data.get("quotes", [])
        except Exception:
            return []

    def _load_group_files(self, group_files: List[Path]) -> List[Dict[str, Any]]:
        quotes = []
        for file in group_files:
            try:
                data = json.loads(file.read_text(encoding="utf-8"))
                raw_quotes = data.get("quotes", [])
                if isinstance(raw_quotes, list):
                    quotes.extend(raw_quotes)
            except Exception:
                continue
        return quotes

    def _group_file(self, group_id: str) -> Path:
        gid = str(group_id or "unknown").strip() or "unknown"
        safe_gid = "".join(ch for ch in gid if ch.isalnum() or ch in ("_", "-"))
        return self.group_dir / f"{safe_gid or 'unknown'}.json"

    def _quotes_for_group(self, group_id: str) -> List[Dict[str, Any]]:
        return [
            q for q in self._cache
            if str(q.get("group", "unknown") or "unknown") == str(group_id or "unknown")
        ]

    def _save_group_file_sync(self, group_id: str, quotes: List[Dict[str, Any]]):
        self.group_dir.mkdir(parents=True, exist_ok=True)
        file = self._group_file(group_id)
        data = {
            "group": str(group_id or "unknown"),
            "quotes": quotes,
        }
        json_str = json.dumps(data, ensure_ascii=False, indent=2)
        fd, tmp_path = tempfile.mkstemp(dir=self.group_dir, text=True, prefix=f"{file.stem}_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(json_str)
            Path(tmp_path).replace(file)
        except Exception as e:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise e

    def _save_all_group_files_sync(self, quotes: List[Dict[str, Any]]):
        by_group: Dict[str, List[Dict[str, Any]]] = {}
        for q in quotes:
            gid = str(q.get("group", "unknown") or "unknown")
            by_group.setdefault(gid, []).append(q)

        for gid, group_quotes in by_group.items():
            self._save_group_file_sync(gid, group_quotes)

    def _rebuild_index(self):
        self._index.clear()
        for q in self._cache:
            gid = str(q.get("group", ""))
            txt = str(q.get("text", "")).strip()
            if gid and txt:
                self._index.add(f"{gid}_{txt}")

    async def _save_group(self, group_id: str):
        async with self._lock:
            self._save_group_file_sync(
                group_id,
                self._quotes_for_group(group_id),
            )

    def _safe_to_quote(self, data: Dict[str, Any]) -> Quote:
        valid_keys = {f.name for f in dataclasses.fields(Quote)}
        clean_data = {k: v for k, v in data.items() if k in valid_keys}

        # 处理嵌套 comments
        raw_comments = clean_data.get("comments", [])
        cmt_objs = []
        for c in raw_comments:
            if isinstance(c, dict):
                cmt_objs.append(Comment(**c))
        clean_data["comments"] = cmt_objs

        return Quote(**clean_data)

    def check_exists(self, group_id: str, text: str) -> bool:
        target_text = text.strip()
        key = f"{group_id}_{target_text}"
        return key in self._index

    async def add_quote(self, quote: Quote) -> bool:
        """
        返回:
        - True: 成功写入
        - False: 已存在（去重）
        """
        key = f"{quote.group}_{quote.text.strip()}"
        if key in self._index:
            return False

        q_dict = dataclasses.asdict(quote)
        self._cache.append(q_dict)
        self._index.add(key)
        await self._save_group(quote.group)
        return True

    async def add_comment(self, qid: str, comment: Comment) -> bool:
        for q in self._cache:
            if q.get("id") == qid:
                if "comments" not in q:
                    q["comments"] = []
                q["comments"].append(dataclasses.asdict(comment))
                await self._save_group(str(q.get("group", "unknown") or "unknown"))
                return True
        return False

    def get_random(self, group_id: Optional[str], qq: Optional[str]) -> Optional[Quote]:
        candidates = []
        for q in self._cache:
            if group_id is not None and str(q.get("group")) != str(group_id):
                continue
            if qq is not None and str(q.get("qq")) != str(qq):
                continue
            candidates.append(q)
        if not candidates:
            return None
        return self._safe_to_quote(random.choice(candidates))

    def get_random_batch(self, group_id: Optional[str], count: int) -> List[Quote]:
        candidates = []
        for q in self._cache:
            if group_id is not None and str(q.get("group")) != str(group_id):
                continue
            candidates.append(q)
        if not candidates:
            return []
        sample_size = min(len(candidates), count)
        selected = random.sample(candidates, sample_size)
        return [self._safe_to_quote(x) for x in selected]

    def get_draw_batch(self, group_id: Optional[str], count: int) -> List[Quote]:
        """抽卡：一人一条优先，最多 count 条，**不重复**。

        - 先每个用户随机抽 1 条（用户与顺序均打乱）。
        - 若仍不足 count，再用各用户剩余的语录（不重复）补足。
        - 候选总数不足 count 时，有几条返回几条，绝不重复同一条。
        """
        candidates = [
            q for q in self._cache
            if group_id is None or str(q.get("group")) == str(group_id)
        ]
        if not candidates:
            return []

        # 按用户分组
        by_user: Dict[str, List[Dict[str, Any]]] = {}
        for q in candidates:
            by_user.setdefault(str(q.get("qq")), []).append(q)

        # 第一轮：一人一条
        users = list(by_user.keys())
        random.shuffle(users)
        picked: List[Dict[str, Any]] = []
        picked_ids = set()
        for u in users:
            q = random.choice(by_user[u])
            picked.append(q)
            picked_ids.add(id(q))

        # 不足则用剩余的（不重复）语录补足
        if len(picked) < count:
            remaining = [q for q in candidates if id(q) not in picked_ids]
            random.shuffle(remaining)
            for q in remaining:
                if len(picked) >= count:
                    break
                picked.append(q)

        random.shuffle(picked)
        selected = picked[:count]
        return [self._safe_to_quote(x) for x in selected]

    def get_user_draw_batch(
        self, group_id: Optional[str], qq: str, count: int
    ) -> List[Quote]:
        """对单个用户抽最多 count 条：**不重复**，不足则有几条出几条。"""
        candidates = []
        for q in self._cache:
            if group_id is not None and str(q.get("group")) != str(group_id):
                continue
            if str(q.get("qq")) != str(qq):
                continue
            candidates.append(q)
        if not candidates:
            return []

        sample_size = min(len(candidates), count)
        selected = random.sample(candidates, sample_size)
        return [self._safe_to_quote(x) for x in selected]

    def get_user_quotes(self, group_id: Optional[str], qq: str) -> List[Quote]:
        res = []
        for q in self._cache:
            if group_id is not None and str(q.get("group")) != str(group_id):
                continue
            if str(q.get("qq")) != str(qq):
                continue
            res.append(self._safe_to_quote(q))
        return res

    async def delete_quote(self, qid: str) -> bool:
        to_delete = next((q for q in self._cache if q.get("id") == qid), None)
        if to_delete:
            gid = str(to_delete.get("group", ""))
            self._cache = [q for q in self._cache if q.get("id") != qid]
            txt = str(to_delete.get("text", "")).strip()
            key = f"{gid}_{txt}"
            if key in self._index:
                self._index.remove(key)
            await self._save_group(gid)
            return True
        return False

    def get_raw_data(self) -> List[Dict[str, Any]]:
        return self._cache
