import asyncio
import logging
import math
from typing import List, Optional

import aiohttp
import chromadb
from llama_index.core import Settings
from llama_index.core.callbacks import CallbackManager, TokenCountingHandler
from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.llms.openai_like import OpenAILike
from llama_index.core.llms import ChatMessage
import openai

from app.core.config import settings

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
        _llm_instance = OpenAILike(
            api_key=settings.API_KEY,
            api_base=settings.API_BASE,
            model=settings.MODEL_NAME,
            temperature=settings.TEMPERATURE,
            max_tokens=settings.MAX_TOKENS,
        )
        logger.info(f"LLM модель успешно загружена: {settings.MODEL_NAME}")
    return _llm_instance


class RAGManager:
    def __init__(self, load_llm: bool = True, load_embeddings: bool = True):
        logger.info("=== Инициализация RAGManager ===")

        if load_llm:
            # Получаем предзагруженную модель
            self.llm = get_llm()
            # Устанавливаем таймауты и повторные попытки
            self.llm.timeout = 60.0  # увеличиваем таймаут до 60 секунд
            self.llm.max_retries = 3
            logger.info("LLM модель получена из кэша")
        else:
            self.llm = None
            logger.info("Загрузка LLM пропущена")

        self.max_retries = 3
        self.base_delay = 1.0

        if load_embeddings:
            # Инициализация OpenAI-совместимой модели эмбеддингов
            self.embed_model = OpenAIEmbedding(
                api_key=settings.API_KEY,
                api_base=settings.API_BASE,
                model_name=settings.MODEL_NAME,
            )
            logger.info(f"Embedding модель инициализирована: {settings.MODEL_NAME}")

            # Создаем настройки по умолчанию
            Settings.llm = self.llm
            Settings.embed_model = self.embed_model
            Settings.chunk_size = 512
            Settings.callback_manager = CallbackManager([TokenCountingHandler()])
            logger.info("Настройки LlamaIndex установлены")
        else:
            self.embed_model = None
            logger.info("Загрузка Embeddings пропущена")

        # Инициализация ChromaDB как клиента
        try:
            self.chroma_client = chromadb.HttpClient(
                host=settings.CHROMA_HOST, port=settings.CHROMA_PORT
            )
            # Создаем единую коллекцию для всех документов
            self.collection = self.chroma_client.get_or_create_collection("documents")
            logger.info(
                f"ChromaDB успешно инициализирован по адресу: http://{settings.CHROMA_HOST}:{settings.CHROMA_PORT}"
            )
        except Exception as e:
            logger.error(f"Ошибка при инициализации ChromaDB: {e}")
            raise

        self.current_context = None  # Добавляем хранение текущего контекста

        logger.info("=== RAGManager успешно инициализирован ===")

    async def check_llm_availability(self) -> bool:
        """Проверка доступности LLM сервера"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{settings.API_BASE}/v1/models") as response:
                    logger.info(f"LLM health check status: {response.status}")
                    return response.status == 200
        except Exception as e:
            logger.error(f"Ошибка при проверке LLM сервера: {e}")
            return False

    async def create_index_for_document(self, document_id: int, content: str) -> None:
        if document_id is None:
            raise ValueError("document_id не может быть None")

        try:
            # Параметры разделения
            chunk_size = 2000
            chunk_overlap = 200
            batch_size = 10  # количество чанков в одной партии
            
            # Генератор чанков для потоковой обработки
            def chunk_generator():
                start = 0
                text_length = len(content)
                
                while start < text_length:
                    end = min(start + chunk_size, text_length)
                    
                    # Ищем ближайший пробел или перенос строки, только если мы не в конце текста
                    if end < text_length:
                        while end > start and not content[end].isspace():
                            end -= 1
                        if end == start:  # Если не нашли пробел, используем исходную границу
                            end = min(start + chunk_size, text_length)
                    
                    # Получаем чанк
                    chunk = content[start:end].strip()
                    if chunk:
                        yield chunk
                    
                    # Если достигли конца текста, выходим
                    if end >= text_length:
                        break
                        
                    # Сдвигаем начало следующего чанка
                    start = end - chunk_overlap

            # Обработка чанков партиями
            current_batch = []
            current_ids = []
            current_metadatas = []
            chunk_index = 0

            for chunk in chunk_generator():
                current_batch.append(chunk)
                current_ids.append(f"doc_{document_id}_{chunk_index}")
                current_metadatas.append({"document_id": document_id, "chunk_index": chunk_index})
                chunk_index += 1

                # Когда набралась партия - отправляем в базу
                if len(current_batch) >= batch_size:
                    await asyncio.sleep(0.1)  # Даем время другим задачам
                    self.collection.add(
                        documents=current_batch,
                        ids=current_ids,
                        metadatas=current_metadatas,
                    )
                    logger.info(f"Добавлена партия из {len(current_batch)} блоков")
                    current_batch = []
                    current_ids = []
                    current_metadatas = []

            # Добавляем оставшиеся чанки
            if current_batch:
                self.collection.add(
                    documents=current_batch,
                    ids=current_ids,
                    metadatas=current_metadatas,
                )
                logger.info(f"Добавлена последняя партия из {len(current_batch)} блоков")

            total_chunks = chunk_index
            logger.info(f"Документ {document_id} успешно разделен на {total_chunks} блоков")

        except Exception as e:
            logger.error(f"Ошибка при добавлении документа в коллекцию: {e}")
            raise

    async def update_document(self, document_id: int, new_content: str) -> None:
        try:
            # Получаем все существующие документы с данным document_id
            existing_docs = self.collection.get(where={"document_id": document_id})
            new_id = f"doc_{document_id}_{len(existing_docs['ids'])}"

            self.collection.add(
                documents=[new_content],
                ids=[new_id],
                metadatas=[{"document_id": document_id}],
            )
            logger.info(f"Документ {document_id} успешно обновлен")
        except Exception as e:
            logger.error(f"Ошибка при обновлении документа: {e}")
            raise

    async def batch_insert_documents(
        self, document_id: int, documents: List[str]
    ) -> None:
        try:
            # Получаем текущее количество документов для данного document_id
            existing_docs = self.collection.get(where={"document_id": document_id})
            current_count = len(existing_docs["ids"])

            all_chunks = []
            all_ids = []
            all_metadatas = []
            all_embeddings = []

            for doc_index, content in enumerate(documents):
                # Разделяем текст на абзацы
                paragraphs = [p.strip() for p in content.split('\n\n') if p.strip()]
                
                # Если абзац слишком длинный, разбиваем его дополнительно
                doc_chunks = []
                for paragraph in paragraphs:
                    if len(paragraph.split()) > Settings.chunk_size:
                        words = paragraph.split()
                        for i in range(0, len(words), Settings.chunk_size):
                            chunk = " ".join(words[i:i + Settings.chunk_size])
                            doc_chunks.append(chunk)
                    else:
                        doc_chunks.append(paragraph)

                # Генерируем эмбеддинги для фрагментов
                for chunk in doc_chunks:
                    embedding = self.embed_model.get_text_embedding(chunk)
                    all_embeddings.append(embedding)

                # Создаем ID и метаданные для каждого фрагмента
                base_index = current_count + sum(len(c) for c in all_chunks)
                chunk_ids = [
                    f"doc_{document_id}_{base_index + i}"
                    for i in range(len(doc_chunks))
                ]
                chunk_metadatas = [
                    {
                        "document_id": document_id,
                        "chunk_index": base_index + i,
                        "doc_index": doc_index,
                    }
                    for i in range(len(doc_chunks))
                ]

                all_chunks.extend(doc_chunks)
                all_ids.extend(chunk_ids)
                all_metadatas.extend(chunk_metadatas)

            self.collection.add(
                documents=all_chunks,
                embeddings=all_embeddings,
                ids=all_ids,
                metadatas=all_metadatas
            )
            
            logger.info(
                f"Пакет документов успешно добавлен для документа {document_id}. "
                f"Создано {len(all_chunks)} фрагментов с эмбеддингами"
            )
        except Exception as e:
            logger.error(f"Ошибка при пакетном добавлении документов: {e}")
            raise

    async def query_document(self, document_id: int, query: str) -> Optional[str]:
        try:
            results = self.collection.query(
                query_texts=[query], where={"document_id": document_id}, n_results=1
            )
            if results and results["documents"][0]:
                return results["documents"][0][0]
            return None
        except Exception as e:
            logger.error(f"Ошибка при выполнении запроса: {e}")
            return None

    def remove_index(self, document_id: int) -> None:
        try:
            # Получаем все ID документов с указанным document_id
            docs = self.collection.get(where={"document_id": document_id})
            if docs["ids"]:
                self.collection.delete(ids=docs["ids"])
            logger.info(f"Документы с ID {document_id} успешно удалены")
        except Exception as e:
            logger.error(f"Ошибка при удалении документов: {e}")
            raise

    def has_index(self, document_id: int) -> bool:
        try:
            docs = self.collection.get(where={"document_id": document_id})
            return len(docs["ids"]) > 0
        except Exception:
            return False

    async def query_all_documents(
        self, query_text: str, chat_history=None, is_new_dialog=True
    ):
        try:
            logger.info("=== Начало обработки запроса к документам ===")

            if not query_text.strip():
                yield "Пожалуйста, введите ваш вопрос."
                return

            if is_new_dialog or self.current_context is None:
                results = self.collection.query(
                    query_texts=[query_text],
                    n_results=10,
                    include=["documents", "distances"],
                )

                if not results or not results["documents"] or not results["documents"][0]:
                    logger.warning("Поиск не вернул результатов")
                    yield "К сожалению, не удалось найти релевантную информацию. Пожалуйста, попробуйте переформулировать вопрос."
                    return

                documents_with_scores = [
                    (doc, 1 / (1 + math.exp(dist - 1)))
                    for doc, dist in zip(results["documents"][0], results["distances"][0])
                ]

                threshold = 0
                filtered_results = [
                    doc for doc, score in documents_with_scores if score > threshold
                ]
                top_3_results = filtered_results[:3]

                if not top_3_results:
                    logger.warning("Не найдено релевантных документов выше порога")
                    yield "Извините, я не нашел достаточно релевантной информации для ответа на ваш вопрос. Пожалуйста, переформулируйте вопрос или уточните детали."
                    return

                self.current_context = "\n".join(top_3_results)
                logger.info(f"Сформирован новый контекст из {len(top_3_results)} наиболее релевантных фрагментов")

            # Формируем базовые сообщения
            messages = [
                ChatMessage(
                    role="system", 
                    content="Ты технический ассистент. Кратко отвечай на вопросы, используя предоставленный контекст."
                )
            ]

            # Добавляем историю сообщений, если она есть
            if chat_history:
                messages.extend([ChatMessage(role=m["role"], content=m["content"]) for m in chat_history])

            # Добавляем текущий контекст и вопрос
            messages.append(
                ChatMessage(
                    role="user",
                    content=f"Контекст:\n{self.current_context}\n\nВопрос: {query_text}"
                )
            )

            logger.info(f"Подготовлены сообщения для запроса к OpenAI. Количество сообщений: {len(messages)}")

            try:
                response = await self.llm.achat(
                    messages=messages,
                    timeout=120,  # явно указываем таймаут
                    stream=True
                )

                if not response or not hasattr(response, 'choices'):
                    logger.error("Получен некорректный ответ от LLM")
                    yield "Произошла ошибка при генерации ответа. Пожалуйста, попробуйте позже."
                    return

                async for chunk in response:
                    if chunk and hasattr(chunk, 'choices') and chunk.choices and \
                       chunk.choices[0].delta and chunk.choices[0].delta.content:
                        yield chunk.choices[0].delta.content
                    await asyncio.sleep(0.05)

            except openai.APITimeoutError as e:
                logger.error(f"Таймаут при запросе к LLM API: {e}", exc_info=True)
                yield "Извините, сервер не отвечает. Пожалуйста, попробуйте позже."
            except Exception as e:
                logger.error(f"Ошибка при генерации ответа: {e}", exc_info=True)
                yield "Произошла ошибка при генерации ответа. Пожалуйста, попробуйте позже."

        except Exception as e:
            logger.error(f"=== Ошибка при запросе к базе документов: {e} ===", exc_info=True)
            yield "Произошла ошибка при обработке запроса. Пожалуйста, попробуйте позже."
