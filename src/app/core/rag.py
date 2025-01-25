from typing import Optional, List, Dict
from llama_index.core import Document, VectorStoreIndex
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.llms.lmstudio import LMStudio
from llama_index.core import Settings
import os
from pathlib import Path
import shutil
import logging
from llama_index.vector_stores.chroma import ChromaVectorStore
import chromadb
import aiohttp
import asyncio

# Настройка логгера
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("rag.log")],
)

logger = logging.getLogger(__name__)


class RAGManager:
    def __init__(self, model_url: str, model_name: str):
        self.model_url = model_url
        self.model_name = model_name
        self.max_retries = 3
        self.base_delay = 1.0

        # Проверяем доступность LLM сервера при инициализации
        logger.info(f"Инициализация LLM с URL: {model_url} и моделью: {model_name}")

        self.llm = LMStudio(
            model_name=model_name,
            base_url=model_url,
            temperature=0.7,
        )

        self.embed_model = HuggingFaceEmbedding(
            model_name="sentence-transformers/all-MiniLM-L6-v2"
        )

        Settings.llm = self.llm
        Settings.embed_model = self.embed_model

        # Инициализация ChromaDB
        self.db_path = Path(__file__).parent.parent.parent / "storage" / "chroma_db"
        self.db_path.mkdir(parents=True, exist_ok=True)

        try:
            self.chroma_client = chromadb.PersistentClient(path=str(self.db_path))
            logger.info(f"ChromaDB успешно инициализирован по пути: {self.db_path}")
        except Exception as e:
            logger.error(f"Ошибка при инициализации ChromaDB: {e}")
            raise

    async def check_llm_availability(self) -> bool:
        """Проверка доступности LLM сервера"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.model_url}/models") as response:
                    logger.info(f"LLM health check status: {response.status}")
                    return response.status == 200
        except Exception as e:
            logger.error(f"Ошибка при проверке LLM сервера: {e}")
            return False

    async def create_index_for_document(self, document_id: int, content: str) -> None:
        if document_id is None:
            raise ValueError("document_id не может быть None")

        collection_name = f"doc_{document_id}"
        try:
            collection = self.chroma_client.get_or_create_collection(collection_name)
            # Добавляем документ в коллекцию
            collection.add(
                documents=[content],
                ids=[f"doc_{document_id}_0"],
                metadatas=[{"document_id": document_id}],
            )
            logger.info(f"Документ успешно добавлен в коллекцию {collection_name}")
        except Exception as e:
            logger.error(f"Ошибка при добавлении документа в коллекцию: {e}")
            raise

    async def update_document(self, document_id: int, new_content: str) -> None:
        collection_name = f"doc_{document_id}"
        try:
            collection = self.chroma_client.get_or_create_collection(collection_name)
            # Генерируем новый ID для документа
            new_id = f"doc_{document_id}_{len(collection.get()['ids'])}"
            collection.add(
                documents=[new_content],
                ids=[new_id],
                metadatas=[{"document_id": document_id}],
            )
            logger.info(f"Документ успешно обновлен в коллекции {collection_name}")
        except Exception as e:
            logger.error(f"Ошибка при обновлении документа: {e}")
            raise

    async def batch_insert_documents(
        self, document_id: int, documents: List[str]
    ) -> None:
        collection_name = f"doc_{document_id}"
        try:
            collection = self.chroma_client.get_or_create_collection(collection_name)
            current_count = len(collection.get()["ids"])

            # Подготовка данных для пакетной вставки
            ids = [
                f"doc_{document_id}_{i + current_count}" for i in range(len(documents))
            ]
            metadatas = [{"document_id": document_id} for _ in documents]

            collection.add(documents=documents, ids=ids, metadatas=metadatas)
            logger.info(
                f"Пакет документов успешно добавлен в коллекцию {collection_name}"
            )
        except Exception as e:
            logger.error(f"Ошибка при пакетном добавлении документов: {e}")
            raise

    async def query_document(self, document_id: int, query: str) -> Optional[str]:
        collection_name = f"doc_{document_id}"
        try:
            collection = self.chroma_client.get_collection(collection_name)
            results = collection.query(query_texts=[query], n_results=1)
            if results and results["documents"][0]:
                return results["documents"][0][0]
            return None
        except Exception as e:
            logger.error(f"Ошибка при выполнении запроса: {e}")
            return None

    def remove_index(self, document_id: int) -> None:
        collection_name = f"doc_{document_id}"
        try:
            self.chroma_client.delete_collection(collection_name)
            logger.info(f"Коллекция {collection_name} успешно удалена")
            logger.info(f"Коллекции: {self.chroma_client.list_collections()}")
        except Exception as e:
            logger.error(f"Ошибка при удалении коллекции: {e}")
            raise

    def has_index(self, document_id: int) -> bool:
        collection_name = f"doc_{document_id}"
        try:
            self.chroma_client.get_collection(collection_name)
            return True
        except Exception:
            return False

    async def query_all_documents(
        self, query: str, chat_history: List[Dict[str, str]] = None
    ) -> str:
        """
        Поиск по всем доступным документам с учетом истории чата
        """
        try:
            # Проверяем доступность LLM сервера перед запросом
            if not await self.check_llm_availability():
                raise Exception("LLM сервер недоступен")

            # Получаем список имен всех коллекций
            collection_names = self.chroma_client.list_collections()

            all_results = []
            # Ищем по каждой коллекции
            for collection_name in collection_names:
                collection = self.chroma_client.get_collection(name=collection_name)
                results = collection.query(
                    query_texts=[query],
                    n_results=2,
                )
                if results["documents"][0]:
                    all_results.extend(results["documents"][0])

            if not all_results:
                return "Не найдено релевантной информации в документах."

            # Формируем контекст из найденных отрывков
            context = "\n".join(all_results)

            # Формируем историю диалога
            conversation = ""
            if chat_history:
                for msg in chat_history:
                    role = "Пользователь" if msg["role"] == "user" else "Ассистент"
                    conversation += f"{role}: {msg['content']}\n"

            # Формируем промпт с контекстом и историей
            prompt = f"""
На основе следующего контекста ответьте на вопрос.
            
Контекст:
{context}

История диалога:
{conversation if chat_history else "История диалога отсутствует"}

Текущий вопрос пользователя: {query}

Отвечай как ассистент технической поддержки, который должен только отвечать на вопросы, которые относятся к документам, которые относятся к контексту.
            """

            logger.info(f"Prompt: {prompt}")
            logger.info(f"Длина промпта: {len(prompt)} символов")

            for attempt in range(self.max_retries):
                try:
                    logger.info(f"Попытка {attempt + 1} отправки запроса к LLM")
                    response = self.llm.complete(prompt)
                    logger.info("Успешно получен ответ от LLM")
                    return response.text
                except Exception as e:
                    logger.error(f"Ошибка при попытке {attempt + 1}: {str(e)}")
                    if attempt == self.max_retries - 1:
                        raise
                    delay = self.base_delay * (2**attempt)
                    logger.warning(f"Ожидание {delay} секунд перед следующей попыткой")
                    await asyncio.sleep(delay)

        except Exception as e:
            logger.error(f"Критическая ошибка при работе с LLM: {str(e)}")
            raise
