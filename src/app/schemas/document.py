from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List

class DocumentBase(BaseModel):
    title: str

class DocumentCreate(DocumentBase):
    file_type: str

class Document(DocumentBase):
    id: int
    file_path: str
    file_type: str
    uploaded_at: datetime
    uploaded_by: int

    class Config:
        from_attributes = True

class UploadError(BaseModel):
    filename: str
    error: str

class UploadSuccess(BaseModel):
    document: Document
    original_filename: str
    was_renamed: bool

class UploadResult(BaseModel):
    success: List[UploadSuccess]
    errors: List[UploadError]
    all_files_uploaded: bool 