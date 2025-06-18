import asyncio
import logging
import math
from typing import List, Optional, AsyncGenerator
from dataclasses import dataclass

import aiohttp
from llama_index.core import Settings, VectorStoreIndex, Document
from llama_index.core.embeddings import BaseEmbedding
from llama_index.core.llms import ChatMessage
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.schema import TextNode
from llama_index.llms.openrouter import OpenRouter
from llama_index.vector_stores.postgres import PGVectorStore

from app.core.config import settings
from app.core.embeddings import CustomEmbedding
from app.core.document_store import DocumentStore
from app.core.query_engine import QueryEngine

# Настройка логгера
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("rag.log")],
)

logger = logging.getLogger(__name__)

# Глобальный экземпляр LLM
_llm_instance = None


def get_llm():
    """Синглтон для получения экземпляра LLM"""

    global _llm_instance
    if _llm_instance is None:
        logger.info("=== Инициализация LLM модели ===")
        _llm_instance = OpenRouter(
            api_key=settings.API_KEY,
            max_tokens=settings.MAX_TOKENS,
            context_window=16 * 1024,
            model=settings.MODEL_NAME,
        )
    print(f"LLM модель: {_llm_instance}")
    print(f"LLM модель: {_llm_instance.model}")
    print(f"LLM модель: {_llm_instance.max_tokens}")
    print(f"LLM модель: {_llm_instance.context_window}")
    print(f"LLM модель: {_llm_instance.api_key}")
    return _llm_instance


@dataclass
class RAGConfig:
    """Конфигурация RAG системы"""

    chunk_size: int = 500
    chunk_overlap: int = 50
    similarity_top_k: int = 3
    embed_dim: int = 1024
    max_retries: int = 20


class RAGManager:
    """Менеджер для работы с RAG системой"""

    def __init__(self, config: Optional[RAGConfig] = None):
        self.config = config or RAGConfig()
        self._initialize_components()

        # Инициализируем text splitter на уровне класса
        self.text_splitter = SentenceSplitter(
            chunk_size=self.config.chunk_size, chunk_overlap=self.config.chunk_overlap
        )
        Settings.text_splitter = self.text_splitter  # Устанавливаем глобально

    def _initialize_components(self) -> None:
        """Инициализация основных компонентов RAG системы"""
        logger.info("Инициализация RAG системы")

        # Инициализация LLM
        self.llm = self._setup_llm()
        Settings.llm = self.llm  # Устанавливаем LLM глобально

        # Инициализация embedding модели
        self.embed_model = CustomEmbedding(settings.EMBEDDING_BASE_URL)
        Settings.embed_model = self.embed_model

        # Инициализация vector store
        self.vector_store = self._setup_vector_store()

        # Инициализация индекса и других компонентов
        self.index = VectorStoreIndex.from_vector_store(
            self.vector_store,
            show_progress=True,
            include_embeddings=True,
            include_text=True,
            include_metadata=True,
            include_keywords=False,
        )
        self.document_store = DocumentStore(self.vector_store, self.config)
        self.query_engine = QueryEngine(
            self.index,
            self.llm,
            similarity_top_k=self.config.similarity_top_k,
            max_retries=self.config.max_retries,
            retry_delay=5.0,
        )

    def _setup_llm(self) -> OpenRouter:
        """Настройка LLM модели"""
        logger.info(f"Настройка LLM модели: {settings.MODEL_NAME}")
        logger.info(
            f"API Key: {'*' * len(settings.API_KEY) if settings.API_KEY else 'Не установлен'}"
        )

        if not settings.API_KEY:
            raise ValueError("API ключ не установлен")

        if not settings.MODEL_NAME:
            raise ValueError("Имя модели не установлено")

        return OpenRouter(
            api_key=settings.API_KEY,
            max_tokens=settings.MAX_TOKENS,
            model=settings.MODEL_NAME,
            temperature=settings.TEMPERATURE,
            base_url="https://openrouter.ai/api/v1",
            timeout=30,
        )

    def _setup_vector_store(self) -> PGVectorStore:
        """Настройка векторного хранилища"""
        return PGVectorStore.from_params(
            host=settings.PGVECTOR_SERVER,
            port=settings.PGVECTOR_PORT,
            user=settings.PGVECTOR_USER,
            password=settings.PGVECTOR_PASSWORD,
            database=settings.PGVECTOR_DB,
            table_name="documents_new",
            embed_dim=self.config.embed_dim,
        )

    async def index_document(self, document_id: int, content: str) -> None:
        """Индексация документа"""
        try:
            await self.document_store.index_document(document_id, content)
            logger.info(f"Документ {document_id} успешно проиндексирован")
        except Exception as e:
            logger.error(f"Ошибка при индексации документа: {e}")
            raise

    async def update_document(self, document_id: int, new_content: str) -> None:
        """Обновление документа"""
        try:
            await self.delete_document(document_id)
            await self.index_document(document_id, new_content)
            logger.info(f"Документ {document_id} успешно обновлен")
        except Exception as e:
            logger.error(f"Ошибка при обновлении документа: {e}")
            raise

    async def delete_document(self, document_id: int) -> None:
        """Удаление документа"""
        try:
            self.vector_store.delete({"filter": {"document_id": document_id}})
            logger.info(f"Документ {document_id} успешно удален")
        except Exception as e:
            logger.error(f"Ошибка при удалении документа: {e}")
            raise

    async def query_documents(
        self,
        query: str,
        chat_history: Optional[List[dict]] = None,
        is_new_dialog: bool = True,
    ) -> AsyncGenerator[str, None]:
        """Поиск ответа на вопрос по документам"""
        try:
            async for chunk in self.query_engine.query(
                query, chat_history, is_new_dialog
            ):
                yield chunk
        except Exception as e:
            logger.error(f"Ошибка при поиске ответа: {e}")
            yield "Произошла ошибка при обработке запроса"

    async def check_system_health(self) -> bool:
        """Проверка здоровья всей системы"""
        try:
            llm_available = await self.query_engine.check_llm_availability()
            vector_store_available = await self.document_store.check_availability()

            return llm_available and vector_store_available
        except Exception as e:
            logger.error(f"Ошибка при проверке здоровья системы: {e}")
            return False

    async def create_index_for_document(self, document_id: int, content: str) -> None:
        """Создание индекса для документа с использованием SentenceSplitter"""
        if document_id is None:
            raise ValueError("document_id не может быть None")

        try:
            # Разбиваем текст на чанки
            text_splitter = SentenceSplitter(
                chunk_size=self.config.chunk_size,
                chunk_overlap=self.config.chunk_overlap,
            )
            text_chunks = text_splitter.split_text(content)

            # Получаем эмбеддинги для всех чанков
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{settings.EMBEDDING_BASE_URL}/embeddings",
                    json={"texts": text_chunks},
                ) as response:
                    data = await response.json()
                    embeddings = data["embeddings"]

            # Создаем ноды с эмбеддингами
            nodes = [
                TextNode(
                    text=chunk,
                    embedding=embedding,
                    metadata={"document_id": document_id},
                )
                for chunk, embedding in zip(text_chunks, embeddings)
            ]

            # Добавляем ноды в vector_store
            if nodes:
                self.vector_store.add(nodes)
                logger.info(
                    f"Документ {document_id} успешно разделен на {len(nodes)} фрагментов"
                )

        except Exception as e:
            logger.error(f"Ошибка при создании индекса документа: {e}")
            raise

    async def batch_insert_documents(
        self, document_id: int, documents: List[str]
    ) -> None:
        try:
            all_nodes = []

            async def get_embeddings_for_chunks(chunks: List[str]) -> List[List[float]]:
                """Вспомогательная функция для получения эмбеддингов для списка фрагментов."""
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.post(
                            f"{settings.EMBEDDING_BASE_URL}/embeddings",
                            json={"texts": chunks},
                        ) as response:
                            if response.status == 200:
                                data = await response.json()
                                if (
                                    "status" in data
                                    and data["status"] == "success"
                                    and "embeddings" in data
                                    and isinstance(data["embeddings"], list)
                                ):
                                    return data["embeddings"]
                                else:
                                    raise ValueError(
                                        f"Некорректный ответ от API эмбеддингов: {data}"
                                    )
                            else:
                                response.raise_for_status()
                except Exception as e:
                    logger.error(f"Ошибка при получении эмбеддингов: {e}")
                    raise

            for doc_index, content in enumerate(documents):
                # Разделяем текст на абзацы
                paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]

                # Если абзац слишком длинный, разбиваем его дополнительно
                doc_chunks = []
                for paragraph in paragraphs:
                    if len(paragraph.split()) > Settings.chunk_size:
                        words = paragraph.split()
                        for i in range(0, len(words), Settings.chunk_size):
                            chunk = " ".join(words[i : i + Settings.chunk_size])
                            doc_chunks.append(chunk)
                    else:
                        doc_chunks.append(paragraph)

                # Получаем эмбеддинги для всех фрагментов сразу
                embeddings = await get_embeddings_for_chunks(doc_chunks)

                # Создаем узлы для каждого фрагмента
                for i, chunk in enumerate(doc_chunks):
                    node = TextNode(
                        text=chunk,
                        id_=f"doc_{document_id}_{doc_index}_{i}",
                        embedding=embeddings[i],
                        metadata={
                            "document_id": document_id,
                            "chunk_index": i,
                            "doc_index": doc_index,
                        },
                    )
                    all_nodes.append(node)

            if all_nodes:  # Проверяем, есть ли фрагменты для добавления
                self.vector_store.add(all_nodes)
                logger.info(
                    f"Пакет документов успешно добавлен в PGVectorStore для документа {document_id}. "
                    f"Создано {len(all_nodes)} фрагментов"
                )

        except Exception as e:
            logger.error(
                f"Ошибка при пакетном добавлении документов в PGVectorStore: {e}"
            )
            raise

    async def query_document(self, document_id: int, query: str) -> Optional[str]:
        """Запрос к PGVectorStore с фильтром по document_id."""
        try:
            from llama_index.core.vector_stores import VectorStoreQuery

            # Получаем эмбеддинг для запроса
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{settings.EMBEDDING_BASE_URL}/embeddings",
                    json={"texts": [query]},
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        query_embedding = data["embeddings"][0]
                    else:
                        logger.error(
                            f"Ошибка при получении эмбеддинга для запроса: {response.status}"
                        )
                        return None

            # Формируем запрос
            query_obj = VectorStoreQuery(
                query_embedding=query_embedding,
                similarity_top_k=1,
                filters={"document_id": document_id},  # Исправленный фильтр
            )
            query_result = self.vector_store.query(query_obj)

            if query_result.nodes:
                return query_result.nodes[0].get_content()
            else:
                return None

        except Exception as e:
            logger.error(f"Ошибка при выполнении запроса к PGVectorStore: {e}")
            return None

    def remove_index(self, document_id: int) -> None:
        """Удаление индекса для документа."""
        try:
            # Используем правильный формат для удаления в PGVectorStore
            self.vector_store.delete(
                ref_doc_id=str(document_id), filter={"document_id": document_id}
            )
            logger.info(f"Индекс для документа {document_id} успешно удален")
        except Exception as e:
            logger.error(f"Ошибка при удалении индекса документа: {e}")
            raise

    def has_index(self, document_id: int) -> bool:
        """Проверяем, есть ли индекс для данного document_id."""
        try:
            # Пытаемся получить документ.  Если его нет, то и индекса нет.
            return (
                self.vector_store.client.query(
                    "SELECT 1 FROM documents_new WHERE document_id = $1 LIMIT 1",
                    document_id,
                ).rowcount
                > 0
            )
        except Exception:
            return False

    async def query_all_documents(
        self, query_text: str, chat_history=None, is_new_dialog=True
    ):
        """Поиск ответа на вопрос по документам"""
        try:
            logger.info("=== Начало обработки запроса к документам ===")

            if not query_text.strip():
                yield "Пожалуйста, введите ваш вопрос."
                return

            # Формируем базовые сообщения
            messages = [
                ChatMessage(
                    role="system",
                    content="Ты технический ассистент. Кратко отвечай на вопросы, используя предоставленный контекст. Отвечай в формате markdown",
                )
            ]

            # Добавляем историю сообщений, если она есть
            if chat_history:
                messages.extend(
                    [
                        ChatMessage(role=m["role"], content=m["content"])
                        for m in chat_history
                    ]
                )

            # Добавляем вопрос
            messages.append(ChatMessage(role="user", content=query_text))

            try:
                # Формируем строку для запроса
                prompt = "\n".join([f"{m.role}: {m.content}" for m in messages])
                logger.info(f"Запрос к LLM API: {prompt}")

                # Используем QueryEngine для получения ответа
                is_first = True
                async for chunk in self.query_engine.query(
                    query_text, chat_history, is_new_dialog
                ):
                    if is_first:
                        yield chunk
                        is_first = False
                    else:
                        yield chunk
                    await asyncio.sleep(0.05)

                # Отправляем маркер конца сообщения
                yield "[END]"

            except asyncio.TimeoutError as e:
                logger.error(f"Таймаут при запросе к LLM API: {e}", exc_info=True)
                yield "Извините, сервер не отвечает. Пожалуйста, попробуйте позже."
                yield "[END]"
            except Exception as e:
                logger.error(f"Ошибка при генерации ответа: {e}", exc_info=True)
                yield "Произошла ошибка при генерации ответа. Пожалуйста, попробуйте позже."
                yield "[END]"

        except Exception as e:
            logger.error(
                f"=== Ошибка при запросе к базе документов: {e} ===", exc_info=True
            )
            yield "Произошла ошибка при обработке запроса. Пожалуйста, попробуйте позже."
            yield "[END]"
