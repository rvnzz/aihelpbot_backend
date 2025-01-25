from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import List
import urllib.parse
from app.core.database import get_db
from app.core.dependencies import check_manager_permission, get_current_user
from app.crud import crud_document
from app.schemas.document import Document, UploadError, UploadResult
from app.models.user import User
from app.core.storage import MinioStorage
import os

router = APIRouter()
storage = MinioStorage()

@router.post("/upload", response_model=UploadResult)
async def create_documents(
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(check_manager_permission)
):
    # Проверяем типы файлов и собираем ошибки
    allowed_types = [".pdf", ".doc", ".docx", ".rtf", ".md"]
    invalid_files = []
    valid_files = []

    for file in files:
        file_ext = os.path.splitext(file.filename)[1].lower()
        if file_ext not in allowed_types:
            invalid_files.append(UploadError(
                filename=file.filename,
                error="Неподдерживаемый тип файла"
            ))
        else:
            valid_files.append(file)

    # Если все файлы невалидны, возвращаем ошибку сразу
    if not valid_files:
        return UploadResult(
            success=[],
            errors=invalid_files,
            all_files_uploaded=False
        )

    # Загружаем валидные файлы
    upload_result = await crud_document.create_documents(
        db=db,
        files=valid_files,
        user_id=current_user.id
    )

    # Добавляем ошибки невалидных файлов к результату
    upload_result.errors.extend(invalid_files)
    upload_result.all_files_uploaded = len(upload_result.errors) == 0

    return upload_result

@router.get("/download/{document_id}")
async def download_document(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    document = crud_document.get_document(db, document_id=document_id)
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Документ не найден"
        )
    
    try:
        file_data, file_size = storage.get_file(document.file_path)
        # URL-кодируем имя файла
        filename = urllib.parse.quote(document.title)
        return StreamingResponse(
            file_data,
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f'attachment; filename*=UTF-8\'\'{filename}{document.file_type}',
                "Content-Length": str(file_size)
            }
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )

@router.get("/", response_model=List[Document])
async def read_documents(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    documents = crud_document.get_documents(db, skip=skip, limit=limit)
    return documents

@router.delete("/{document_id}")
async def delete_document(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(check_manager_permission)
):
    success = await crud_document.delete_document(db, document_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Документ не найден"
        )
    return {"message": "Документ успешно удален"} 