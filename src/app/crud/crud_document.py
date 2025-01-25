import os
from typing import List, Optional
import tempfile

import logging
from fastapi import UploadFile
from llama_index.core import SimpleDirectoryReader
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rag import RAGManager
from app.core.storage import MinioStorage
from app.models.document import Document
from app.schemas.document import (
    DocumentCreate,
    UploadError,
    UploadResult,
    UploadSuccess,
)

storage = MinioStorage()

logger = logging.getLogger(__name__)

# Инициализируем RAG менеджер
rag_manager = RAGManager(
    model_url=settings.LLM_API_URL, model_name=settings.LLM_MODEL_NAME
)


def get_document(db: Session, document_id: int) -> Optional[Document]:
    return db.query(Document).filter(Document.id == document_id).first()


def get_documents(db: Session, skip: int = 0, limit: int = 100) -> List[Document]:
    return db.query(Document).offset(skip).limit(limit).all()


def get_unique_title(db: Session, base_title: str) -> str:
    """Генерирует уникальное имя для документа, если такое имя уже существует"""
    title = base_title
    counter = 1
    while db.query(Document).filter(Document.title == title).first():
        # Разделяем имя файла и расширение
        name, ext = os.path.splitext(base_title)
        title = f"{name} ({counter}){ext}"
        counter += 1
    return title


async def create_documents(
    db: Session, files: List[UploadFile], user_id: int
) -> UploadResult:
    successful_documents = []
    errors = []
    temp_documents = []
    uploaded_files = []  # Список для отслеживания загруженных в Minio файлов

    for file in files:
        try:
            file_ext = os.path.splitext(file.filename)[1].lower()
            if not file_ext:
                file_ext = ".unknown"

            base_name = os.path.splitext(file.filename)[0]
            original_title = base_name
            title = get_unique_title(db, base_name)

            # Загружаем файл в Minio
            object_name = await storage.upload_file(file)
            uploaded_files.append(
                object_name
            )  # Сохраняем имя файла для возможной очистки

            # Создаем запись в БД, но пока не делаем коммит
            db_document = Document(
                title=title,
                file_path=object_name,
                file_type=file_ext,
                uploaded_by=user_id,
            )
            db.add(db_document)

            # Извлекаем текст из документа
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = os.path.join(temp_dir, title + file_ext)
                await file.seek(0)
                content = await file.read()

                with open(temp_path, "wb") as temp_file:
                    temp_file.write(content)

                reader = SimpleDirectoryReader(input_files=[temp_path])
                documents = reader.load_data()
                content_text = " ".join([doc.text for doc in documents])

            # Сохраняем информацию о документе
            temp_documents.append(
                {
                    "document": db_document,
                    "original_filename": file.filename,
                    "was_renamed": original_title != title,
                    "content_text": content_text,
                    "object_name": object_name,
                }
            )

        except Exception as e:
            # Откатываем все изменения в БД
            db.rollback()

            # Удаляем все загруженные файлы из Minio
            for uploaded_file in uploaded_files:
                try:
                    storage.delete_file(uploaded_file)
                except Exception as delete_error:
                    logger.error(f"Ошибка при удалении файла из Minio: {delete_error}")

            errors.append(UploadError(filename=file.filename, error=str(e)))
            continue

    # Если есть успешно обработанные документы, пытаемся сохранить их
    if temp_documents:
        try:
            # Делаем коммит в БД
            db.commit()

            # После коммита обновляем объекты документов, чтобы получить их ID
            for doc_info in temp_documents:
                db.refresh(doc_info["document"])

            # Теперь создаем индексы RAG, когда у документов есть ID
            for doc_info in temp_documents:
                await rag_manager.create_index_for_document(
                    doc_info["document"].id, doc_info["content_text"]
                )
                successful_documents.append(
                    UploadSuccess(
                        document=doc_info["document"],
                        original_filename=doc_info["original_filename"],
                        was_renamed=doc_info["was_renamed"],
                    )
                )

        except Exception as e:
            # В случае ошибки откатываем изменения
            db.rollback()

            # Удаляем все загруженные файлы из Minio
            for doc_info in temp_documents:
                try:
                    storage.delete_file(doc_info["object_name"])
                except Exception as delete_error:
                    logger.error(f"Ошибка при удалении файла из Minio: {delete_error}")

            # Добавляем все документы в список ошибок
            for doc_info in temp_documents:
                errors.append(
                    UploadError(
                        filename=doc_info["original_filename"],
                        error=f"Ошибка при сохранении в базу данных: {str(e)}",
                    )
                )

    return UploadResult(
        success=successful_documents, errors=errors, all_files_uploaded=len(errors) == 0
    )


async def delete_document(db: Session, document_id: int):
    document = get_document(db, document_id)
    if document:
        try:
            # Удаляем RAG индекс
            rag_manager.remove_index(document_id)

            # Проверяем, что индекс действительно удален
            if rag_manager.has_index(document_id):
                raise Exception("Индекс не был удален корректно")

            # Удаляем файл из Minio
            storage.delete_file(document.file_path)

            # Удаляем запись из базы данных
            db.delete(document)
            db.commit()
            return True

        except Exception as e:
            db.rollback()
            raise Exception(f"Ошибка при удалении документа: {str(e)}")
    return False


# TODO: Сделать чтение файлов через https://llamahub.ai/l/readers/llama-index-readers-file?from=readers. Готово
# TODO: Проверить сохраняется ли RAG при добавлении документа и убирается ли при удалении Готово
# TODO: Проверить работоспособность RAG Готово
# TODO: Проверить работу websocket Готово
# TODO: Проверить чат на работоспособность Готово
# TODO: Сделать чтобы он указывал из кокого документа он берет информацию
# TODO: Сделать чтобы он отвечал только на вопросы, которые относятся к документам, которые есть в базе Готово
