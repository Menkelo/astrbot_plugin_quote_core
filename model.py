from dataclasses import dataclass, field
from typing import Optional, List

@dataclass
class Comment:
    qq: str
    name: str
    text: str
    created_at: float

@dataclass
class Quote:
    id: str
    qq: str
    name: str
    text: str
    created_by: str
    created_at: float
    group: str         
    ai_reason: Optional[str] = None 
    comments: List[Comment] = field(default_factory=list)