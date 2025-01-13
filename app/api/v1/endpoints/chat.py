import json

from fastapi import APIRouter, Depends, WebSocket
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import get_current_user_ws
from app.core.rag import RAGManager
from app.crud import crud_document

router = APIRouter()

# Инициализируем RAG менеджер
rag_manager = RAGManager(
    model_url=settings.LLM_API_URL, model_name=settings.LLM_MODEL_NAME
)


@router.websocket("/ws/{document_id}")
async def chat_endpoint(
    websocket: WebSocket, document_id: int, db: Session = Depends(get_db)
):
    await websocket.accept()

    try:
        # Аутентификация пользователя
        user = await get_current_user_ws(websocket, db)
        if not user:
            await websocket.close(code=1008, reason="Unauthorized")
            return

        # Получаем документ
        document = crud_document.get_document(db, document_id)
        if not document:
            await websocket.close(code=1008, reason="Document not found")
            return

        while True:
            # Получаем сообщение от клиента
            message = await websocket.receive_text()

            try:
                # Выполняем запрос к RAG
                response = await rag_manager.query_document(document_id, message)

                if response:
                    await websocket.send_text(
                        json.dumps({"type": "response", "content": response})
                    )
                else:
                    await websocket.send_text(
                        json.dumps(
                            {
                                "type": "error",
                                "content": "Индекс для документа не найден",
                            }
                        )
                    )

            except Exception as e:
                await websocket.send_text(
                    json.dumps({"type": "error", "content": str(e)})
                )

    except Exception as e:
        await websocket.close(code=1011, reason=str(e))
