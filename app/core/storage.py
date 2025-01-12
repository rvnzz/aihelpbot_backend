from minio import Minio
from minio.error import S3Error
from fastapi import UploadFile
from app.core.config import settings
import io
import uuid

class MinioStorage:
    def __init__(self):
        self.client = Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ROOT_USER,
            secret_key=settings.MINIO_ROOT_PASSWORD,
            secure=settings.MINIO_SECURE
        )
        self.bucket_name = settings.MINIO_BUCKET_NAME
        self._ensure_bucket_exists()

    def _ensure_bucket_exists(self):
        """Проверяет существование корзины и создает её при необходимости"""
        try:
            if not self.client.bucket_exists(self.bucket_name):
                self.client.make_bucket(self.bucket_name)
        except S3Error as e:
            raise Exception(f"Ошибка при инициализации Minio: {str(e)}")

    async def upload_file(self, file: UploadFile) -> str:
        """Загружает файл в Minio и возвращает его уникальный идентификатор"""
        try:
            # Генерируем уникальное имя файла
            file_ext = file.filename.split('.')[-1]
            object_name = f"{uuid.uuid4()}.{file_ext}"
            
            # Читаем содержимое файла
            content = await file.read()
            content_bytes = io.BytesIO(content)
            
            # Загружаем файл в Minio
            self.client.put_object(
                self.bucket_name,
                object_name,
                content_bytes,
                length=len(content)
            )
            
            return object_name
        except S3Error as e:
            raise Exception(f"Ошибка при загрузке файла: {str(e)}")

    def get_file(self, object_name: str) -> tuple[io.BytesIO, int]:
        """Получает файл из Minio"""
        try:
            # Получаем объект
            data = self.client.get_object(self.bucket_name, object_name)
            # Читаем содержимое в память
            content = data.read()
            return io.BytesIO(content), len(content)
        except S3Error as e:
            raise Exception(f"Ошибка при получении файла: {str(e)}")

    def delete_file(self, object_name: str):
        """Удаляет файл из Minio"""
        try:
            self.client.remove_object(self.bucket_name, object_name)
        except S3Error as e:
            raise Exception(f"Ошибка при удалении файла: {str(e)}") 