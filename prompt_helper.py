import json
import ast
import re
from typing import List, Dict


def build_system_prompt(max_quotes: int, template: str) -> str:
    if not template:
        return ""
    return (
        template
        .replace("{max_quotes}", str(max_quotes))
        .replace("${max_golden_quotes}", str(max_quotes))
        .replace("${messages_text}", "")
    )


def build_user_prompt(context_str: str, target_name: str = None) -> str:
    target_desc = (
        f"本次只分析目标用户 **{target_name}** 的发言。"
        if target_name
        else "本次分析所有人的发言。"
    )

    prompt = (
        "## 待分析的群聊记录\n"
        f"{target_desc}\n\n"
        "请严格按照系统提示词中的标准筛选，不要为了凑数量而选择普通内容。\n"
        "如果没有足够逆天、足够有冲击力的发言，请返回空数组 []。\n\n"
        "## 群聊记录\n"
        f"{context_str}"
    )

    return prompt


def parse_json(resp) -> List[Dict]:
    if not resp:
        return []

    text = getattr(resp, "completion_text", None) or getattr(resp, "text", None)
    if not text:
        return []

    text = text.strip()
    text = text.replace("```json", "").replace("```", "").strip()

    match = re.search(r"(\[.*\]|\{.*\})", text, re.DOTALL)
    json_str = match.group(1) if match else text

    try:
        return json.loads(json_str)
    except:
        try:
            return ast.literal_eval(json_str)
        except:
            return []
