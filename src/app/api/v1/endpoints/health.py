from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from typing import Dict, List, Optional, Any
import chromadb
import numpy as np
from app.core.config import settings
from app.core.rag import RAGManager

router = APIRouter()
rag_manager = RAGManager(load_llm=True, load_embeddings=False)

class DocumentData(BaseModel):
    id: str
    text: str
    metadata: Dict[str, Any]
    embedding: Optional[List[float]]

class CollectionData(BaseModel):
    name: str
    count: int
    metadata: Dict = {}
    documents: List[DocumentData]

class ChromaMetrics(BaseModel):
    collections: List[CollectionData]
    total_documents: int

class HealthResponse(BaseModel):
    status: str
    details: Dict[str, str]

class ChromaResponse(BaseModel):
    status: str
    details: Dict[str, str]
    metrics: ChromaMetrics

@router.get("/chroma", response_model=ChromaResponse)
async def check_chroma_health(
    include_embeddings: bool = Query(False, description="Включить векторы эмбеддингов в ответ"),
    limit: int = Query(100, description="Максимальное количество документов для каждой коллекции")
):
    """
    Проверяет состояние ChromaDB и возвращает подробную информацию о документах
    """
    try:
        client = chromadb.HttpClient(
            host=settings.CHROMA_HOST,
            port=settings.CHROMA_PORT
        )
        
        collections = client.list_collections()
        collection_data = []
        total_docs = 0
        
        for collection in collections:
            count = collection.count()
            total_docs += count
            
            # Получаем все документы из коллекции с ограничением
            result = collection.get(
                limit=limit,
                include=['documents', 'metadatas', 'embeddings'] if include_embeddings else ['documents', 'metadatas']
            )
            
            documents = []
            for i in range(len(result['ids'])):
                doc_data = DocumentData(
                    id=result['ids'][i],
                    text=result['documents'][i],
                    metadata=result['metadatas'][i] if result['metadatas'][i] else {},
                    embedding=result['embeddings'][i].tolist() if include_embeddings and 'embeddings' in result else None
                )
                documents.append(doc_data)
            
            collection_data.append(
                CollectionData(
                    name=collection.name,
                    count=count,
                    metadata=collection.metadata or {},
                    documents=documents
                )
            )
        
        metrics = ChromaMetrics(
            collections=collection_data,
            total_documents=total_docs
        )
        
        return ChromaResponse(
            status="healthy",
            details={
                "connection": "ok",
                "collections_count": str(len(collections)),
                "documents_returned": f"Showing up to {limit} documents per collection"
            },
            metrics=metrics
        )
    except Exception as e:
        return ChromaResponse(
            status="unhealthy",
            details={
                "error": str(e)
            },
            metrics=ChromaMetrics(collections=[], total_documents=0)
        )

# Добавим эндпоинт для получения конкретной коллекции
@router.get("/chroma/{collection_name}", response_model=CollectionData)
async def get_collection_details(
    collection_name: str,
    include_embeddings: bool = Query(False, description="Включить векторы эмбеддингов в ответ"),
    limit: int = Query(100, description="Максимальное количество документов"),
    offset: int = Query(0, description="Смещение для пагинации")
):
    """
    Получает подробную информацию о конкретной коллекции
    """
    try:
        client = chromadb.HttpClient(
            host=settings.CHROMA_HOST,
            port=settings.CHROMA_PORT
        )
        
        collection = client.get_collection(collection_name)
        count = collection.count()
        
        result = collection.get(
            limit=limit,
            offset=offset,
            include=['documents', 'metadatas', 'embeddings'] if include_embeddings else ['documents', 'metadatas']
        )
        
        documents = []
        for i in range(len(result['ids'])):
            doc_data = DocumentData(
                id=result['ids'][i],
                text=result['documents'][i],
                metadata=result['metadatas'][i] if result['metadatas'][i] else {},
                embedding=result['embeddings'][i].tolist() if include_embeddings and 'embeddings' in result else None
            )
            documents.append(doc_data)
        
        return CollectionData(
            name=collection_name,
            count=count,
            metadata=collection.metadata or {},
            documents=documents
        )
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.get("/llm", response_model=HealthResponse)
async def check_llm_health():
    """
    Проверяет доступность LLM сервера
    """
    try:
        # Используем существующий метод проверки LLM
        is_available = await rag_manager.check_llm_availability()
        
        if is_available:
            return HealthResponse(
                status="healthy",
                details={
                    "connection": "ok",
                    "model": settings.MODEL_NAME,
                    "api_base": settings.API_BASE
                }
            )
        else:
            return HealthResponse(
                status="unhealthy",
                details={
                    "error": "LLM сервер недоступен"
                }
            )
    except Exception as e:
        return HealthResponse(
            status="unhealthy",
            details={
                "error": str(e)
            }
        )

@router.get("/", response_model=HealthResponse)
async def check_overall_health():
    """
    Проверяет общее состояние всех компонентов
    """
    chroma_health = await check_chroma_health()
    llm_health = await check_llm_health()
    
    overall_status = "healthy" if (
        chroma_health.status == "healthy" and 
        llm_health.status == "healthy"
    ) else "unhealthy"
    
    return HealthResponse(
        status=overall_status,
        details={
            "chroma": chroma_health.status,
            "llm": llm_health.status
        }
    ) 