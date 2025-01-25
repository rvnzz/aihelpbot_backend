import json

from fastapi import APIRouter, Depends, WebSocket, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import get_current_user, get_current_user_ws
from app.core.rag import RAGManager
from app.crud import crud_document, crud_chat
from app.schemas.chat import Chat, ChatCreate, ChatMessage, ChatBrief

router = APIRouter()

# Инициализируем RAG менеджер
rag_manager = RAGManager(
    model_url=settings.LLM_API_URL, model_name=settings.LLM_MODEL_NAME
)


@router.post("/", response_model=Chat)
async def create_chat(
    chat: ChatCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return crud_chat.create_chat(db=db, user_id=current_user.id, title=chat.title)


@router.get("/", response_model=List[ChatBrief])
async def get_chats(
    db: Session = Depends(get_db), current_user=Depends(get_current_user)
):
    return crud_chat.get_user_chats(db=db, user_id=current_user.id)


@router.websocket("/ws/{chat_id}")
async def chat_endpoint(
    websocket: WebSocket, chat_id: int, db: Session = Depends(get_db)
):
    await websocket.accept()

    try:
        # Аутентификация пользователя
        user = await get_current_user_ws(websocket, db)
        if not user:
            await websocket.close(code=1008, reason="Unauthorized")
            return

        # Проверяем существование чата и права доступа
        chat = crud_chat.get_chat(db, chat_id)
        if not chat or chat.user_id != user.id:
            await websocket.close(code=1008, reason="Chat not found or access denied")
            return

        while True:
            message = await websocket.receive_text()

            try:
                # Получаем последние сообщения чата (например, последние 10)
                chat_history = crud_chat.get_chat_messages(db, chat_id, limit=10)

                # Форматируем историю чата для промпта
                formatted_history = []
                for msg in reversed(
                    chat_history
                ):  # Разворачиваем, чтобы получить хронологический порядок
                    role = "user" if msg.is_user else "assistant"
                    formatted_history.append({"role": role, "content": msg.content})

                # Добавляем текущее сообщение
                formatted_history.append({"role": "user", "content": message})

                # Сохраняем сообщение пользователя
                user_message = crud_chat.add_message(
                    db=db, chat_id=chat_id, content=message, is_user=True
                )

                # Получаем ответ от RAG, передавая историю
                response = await rag_manager.query_all_documents(
                    message, chat_history=formatted_history
                )

                if response:
                    # Сохраняем ответ системы
                    system_message = crud_chat.add_message(
                        db=db, chat_id=chat_id, content=response, is_user=False
                    )
                    await websocket.send_text(
                        json.dumps(
                            {
                                "type": "response",
                                "content": response,
                                "messageId": system_message.id,
                            }
                        )
                    )
                else:
                    await websocket.send_text(
                        json.dumps(
                            {
                                "type": "error",
                                "content": "Не найдено релевантной информации в документах",
                            }
                        )
                    )

            except Exception as e:
                await websocket.send_text(
                    json.dumps({"type": "error", "content": str(e)})
                )

    except Exception as e:
        await websocket.close(code=1011, reason=str(e))


@router.get("/{chat_id}/history", response_model=List[ChatMessage])
async def get_chat_history(
    chat_id: int, db: Session = Depends(get_db), current_user=Depends(get_current_user)
):
    # Проверяем существование чата и права доступа
    chat = crud_chat.get_chat(db, chat_id)
    if not chat:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Чат не найден"
        )
    if chat.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Нет доступа к этому чату"
        )

    # Получаем историю сообщений в хронологическом порядке (от старых к новым)
    messages = crud_chat.get_chat_messages(db, chat_id, ascending=True)
    return messages


@router.get("/{chat_id}", response_model=ChatBrief)
async def get_chat(
    chat_id: int, db: Session = Depends(get_db), current_user=Depends(get_current_user)
):
    # Проверяем существование чата
    chat = crud_chat.get_chat(db, chat_id)
    if not chat:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Чат не найден"
        )

    # Проверяем права доступа
    if chat.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Нет доступа к этому чату"
        )

    return chat


@router.put("/{chat_id}/rename")
async def rename_chat(
    chat_id: int,
    title: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    # Проверяем существование чата
    chat = crud_chat.get_chat(db, chat_id)
    if not chat:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Чат не найден"
        )

    # Проверяем права доступа
    if chat.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Нет доступа к этому чату"
        )

    # Переименовываем чат
    updated_chat = crud_chat.rename_chat(db, chat_id, title)
    return updated_chat
