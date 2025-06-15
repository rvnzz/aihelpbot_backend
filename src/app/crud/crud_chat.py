from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.chat import Chat, ChatMessage


def create_chat(db: Session, user_id: int, title: str = "Новый чат") -> Chat:
    db_chat = Chat(title=title, user_id=user_id)
    db.add(db_chat)
    db.commit()
    db.refresh(db_chat)
    return db_chat


def get_user_chats(db: Session, user_id: int) -> List[Chat]:
    return db.query(Chat).filter(Chat.user_id == user_id).all()


def get_chat(db: Session, chat_id: int) -> Optional[Chat]:
    return db.query(Chat).filter(Chat.id == chat_id).first()


def add_message(db: Session, chat_id: int, content: str, is_user: bool) -> ChatMessage:
    message = ChatMessage(content=content, is_user=is_user, chat_id=chat_id)
    db.add(message)
    db.commit()
    db.refresh(message)
    return message


def get_chat_messages(
    db: Session, chat_id: int, limit: int = 100, ascending: bool = False
) -> List[ChatMessage]:
    query = db.query(ChatMessage).filter(ChatMessage.chat_id == chat_id)

    if ascending:
        query = query.order_by(ChatMessage.created_at.asc())
    else:
        query = query.order_by(ChatMessage.created_at.desc())

    return query.limit(limit).all()


def rename_chat(db: Session, chat_id: int, new_title: str) -> Chat:
    chat = db.query(Chat).filter(Chat.id == chat_id).first()
    if chat:
        chat.title = new_title
        db.commit()
        db.refresh(chat)
    return chat


def update_message(db: Session, message_id: int, content: str):
    message = db.query(ChatMessage).filter(ChatMessage.id == message_id).first()
    if message:
        message.content = content
        db.commit()
        db.refresh(message)
    return message


def delete_chat(db: Session, chat_id: int) -> bool:
    chat = db.query(Chat).filter(Chat.id == chat_id).first()
    if chat:
        db.delete(chat)
        db.commit()
        return True
    return False
