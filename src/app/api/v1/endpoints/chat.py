import json
import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, WebSocket, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user, get_current_user_ws
from app.core.rag import RAGManager
from app.crud import crud_chat
from app.schemas.chat import Chat, ChatBrief, ChatCreate, ChatMessage

router = APIRouter()

# Инициализируем RAG менеджер
rag_manager = RAGManager()


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
    logger = logging.getLogger(__name__)
    logger.info(f"Новое WebSocket подключение для чата {chat_id}")

    connection_active = True

    try:
        await websocket.accept()
        logger.info(f"WebSocket соединение принято для чата {chat_id}")

        # Аутентификация пользователя
        user = await get_current_user_ws(websocket, db)
        if not user:
            logger.warning(f"Неавторизованная попытка доступа к чату {chat_id}")
            await websocket.close(code=1008, reason="Unauthorized")
            connection_active = False
            return
        logger.info(f"Пользователь {user.email} авторизован для чата {chat_id}")

        # Проверяем существование чата и права доступа
        chat = crud_chat.get_chat(db, chat_id)
        if not chat or chat.user_id != user.id:
            logger.warning(
                f"Попытка доступа к несуществующему чату или отказ в доступе: {chat_id}"
            )
            await websocket.close(code=1008, reason="Chat not found or access denied")
            connection_active = False
            return
        logger.info(
            f"Доступ к чату {chat_id} подтвержден для пользователя {user.email}"
        )

        while connection_active:
            try:
                message = await websocket.receive_text()
                logger.info(
                    f"Получено сообщение в чате {chat_id} от пользователя {user.email}"
                )

                # Получаем последние сообщения чата
                chat_history = crud_chat.get_chat_messages(db, chat_id, limit=10)
                logger.debug(
                    f"Получена история чата {chat_id}, {len(chat_history)} сообщений"
                )

                # Форматируем историю чата для промпта
                formatted_history = []
                for msg in reversed(chat_history):
                    role = "user" if msg.is_user else "assistant"
                    formatted_history.append({"role": role, "content": msg.content})
                logger.debug(
                    f"История чата отформатирована, {len(formatted_history)} сообщений"
                )

                # Добавляем текущее сообщение
                formatted_history.append({"role": "user", "content": message})

                # Сохраняем сообщение пользователя
                user_message = crud_chat.add_message(
                    db=db, chat_id=chat_id, content=message, is_user=True
                )
                logger.info(f"Сообщение пользователя сохранено с ID {user_message.id}")

                # Сохраняем начальное системное сообщение
                system_message = crud_chat.add_message(
                    db=db, chat_id=chat_id, content="", is_user=False
                )
                logger.info(
                    f"Создано пустое системное сообщение с ID: {system_message.id}"
                )

                # Получаем потоковый ответ от RAG
                logger.info("=== Начало получения ответа от RAG ===")
                response_stream = rag_manager.query_all_documents(
                    message, chat_history=formatted_history
                )
                logger.info(f"Тип response_stream: {type(response_stream)}")

                full_response = ""
                chunk_counter = 0

                logger.info("=== Начало обработки потока ответов ===")
                async for complete_response in response_stream:
                    if not connection_active:
                        break

                    chunk_counter += 1
                    logger.info(f"=== Обработка ответа {chunk_counter} ===")

                    # Отправляем текущее состояние ответа клиенту
                    message_data = json.dumps(
                        {
                            "type": "stream",
                            "content": complete_response,
                            "messageId": system_message.id,
                        }
                    )

                    await websocket.send_text(message_data)
                    full_response += complete_response  # Накапливаем полный ответ

                if not connection_active:
                    break

                logger.info(
                    f"=== Генерация завершена, всего обновлений: {chunk_counter} ==="
                )

                if full_response:
                    logger.info("=== Обновление финального ответа ===")
                    # Обновляем существующее сообщение вместо создания нового
                    system_message = crud_chat.update_message(
                        db=db, message_id=system_message.id, content=full_response
                    )
                    logger.info(f"Ответ обновлен в БД с ID: {system_message.id}")

                    if connection_active:
                        logger.info("Отправка финального WebSocket сообщения...")
                        await websocket.send_text(
                            json.dumps(
                                {
                                    "type": "response",
                                    "content": full_response,
                                    "messageId": system_message.id,
                                }
                            )
                        )
                        logger.info("Финальное сообщение отправлено")

            except WebSocketDisconnect as e:
                logger.info(
                    f"WebSocket соединение закрыто клиентом: {e.code} - {e.reason}"
                )
                connection_active = False
                break
            except Exception as e:
                logger.error(f"Ошибка при обработке сообщения: {str(e)}", exc_info=True)
                if connection_active:
                    try:
                        await websocket.send_text(
                            json.dumps({"type": "error", "content": str(e)})
                        )
                    except Exception:
                        connection_active = False
                        break

    except WebSocketDisconnect as e:
        logger.info(f"WebSocket соединение закрыто: {e.code} - {e.reason}")
    except Exception as e:
        logger.error(
            f"Критическая ошибка в WebSocket соединении: {str(e)}", exc_info=True
        )
        if connection_active:
            try:
                await websocket.close(code=1011, reason=str(e))
            except Exception:
                pass


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


@router.delete("/{chat_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chat(
    chat_id: int,
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

    # Удаляем чат
    if not crud_chat.delete_chat(db, chat_id):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Ошибка при удалении чата",
        )
