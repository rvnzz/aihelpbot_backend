from pydantic import BaseModel
from datetime import datetime
from typing import List, Optional


class ChatMessageBase(BaseModel):
    content: str
    is_user: bool = True


class ChatMessage(ChatMessageBase):
    id: int
    created_at: datetime
    chat_id: int

    class Config:
        from_attributes = True


class ChatBase(BaseModel):
    title: str


class ChatCreate(ChatBase):
    pass


class Chat(ChatBase):
    id: int
    created_at: datetime
    user_id: int
    messages: List[ChatMessage] = []

    class Config:
        from_attributes = True


class ChatHistory(BaseModel):
    messages: List[ChatMessage]


class ChatBrief(BaseModel):
    id: int
    title: str
    user_id: int
    created_at: datetime

    class Config:
        from_attributes = True
