from sqlalchemy.orm import Session
from app.models.document import Document
from app.schemas.document import DocumentCreate, UploadError, UploadResult, UploadSuccess
from typing import List, Optional
from fastapi import UploadFile
from datetime import datetime
from app.core.storage import MinioStorage
import os

storage = MinioStorage()

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
    db: Session, 
    files: List[UploadFile], 
    user_id: int
) -> UploadResult:
    successful_documents = []
    errors = []
    temp_documents = []  # Временный список для документов до коммита

    for file in files:
        try:
            # Получаем расширение файла
            file_ext = os.path.splitext(file.filename)[1].lower()
            if not file_ext:
                file_ext = '.unknown'
                
            # Используем имя файла как заголовок (без расширения)
            base_name = os.path.splitext(file.filename)[0]
            original_title = base_name
            title = get_unique_title(db, base_name)
            
            document = DocumentCreate(
                title=title,
                file_type=file_ext
            )
            
            # Загружаем файл в Minio
            object_name = await storage.upload_file(file)
            
            # Создаем запись в базе данных
            db_document = Document(
                title=document.title,
                file_path=object_name,
                file_type=document.file_type,
                uploaded_by=user_id
            )
            db.add(db_document)
            
            # Сохраняем документ и информацию о переименовании
            temp_documents.append({
                "document": db_document,
                "original_filename": file.filename,
                "was_renamed": original_title != title
            })
            
        except Exception as e:
            # В случае ошибки добавляем информацию об ошибке
            errors.append(UploadError(
                filename=file.filename,
                error=str(e)
            ))
            # Если произошла ошибка после загрузки в Minio, но до сохранения в БД,
            # пытаемся удалить файл из Minio
            if 'object_name' in locals():
                try:
                    storage.delete_file(object_name)
                except:
                    pass

    # Сохраняем успешно загруженные документы
    if temp_documents:
        try:
            db.commit()
            # После коммита создаем UploadSuccess объекты
            for doc_info in temp_documents:
                db.refresh(doc_info["document"])
                successful_documents.append(UploadSuccess(
                    document=doc_info["document"],
                    original_filename=doc_info["original_filename"],
                    was_renamed=doc_info["was_renamed"]
                ))
        except Exception as e:
            # Если произошла ошибка при коммите, добавляем все документы в ошибки
            for doc_info in temp_documents:
                errors.append(UploadError(
                    filename=doc_info["original_filename"],
                    error=f"Ошибка при сохранении в базу данных: {str(e)}"
                ))

    return UploadResult(
        success=successful_documents,
        errors=errors,
        all_files_uploaded=len(errors) == 0
    )

async def delete_document(db: Session, document_id: int):
    document = get_document(db, document_id)
    if document:
        # Удаляем файл из Minio
        storage.delete_file(document.file_path)
        # Удаляем запись из базы данных
        db.delete(document)
        db.commit()
        return True
    return False 