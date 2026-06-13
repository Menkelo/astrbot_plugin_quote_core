import unicodedata
import re

def is_valid_nickname(name: str) -> bool:
    """
    [NapCat适配] 判断昵称是否包含实质性的可见字符
    防止出现空白名字
    """
    if not name or not name.strip(): return False
    
    for char in name:
        # 过滤 Hangul Filler, Braille Pattern Blank 等隐形字符
        if char in ('\u3164', '\u2800', '\u115f', '\u1160', '\uffa0'):
            continue
        
        cat = unicodedata.category(char)
        # C = Control(控制), Z = Separator(分隔)
        if cat.startswith('C') or cat.startswith('Z'):
            continue
            
        # 只要找到一个可见字符(L字母, N数字, P标点, S符号)，即有效
        return True
    return False

def extract_plaintext(message_chain: list) -> str:
    """
    从 OneBot 消息链中提取纯文本
    """
    if not message_chain: return ""
    try:
        return "".join([str(m.get("data", {}).get("text", "")) 
                       for m in message_chain 
                       if m.get("type") in ("text", "plain")]).strip()
    except:
        return ""