import aiohttp
import logging
import asyncio
from typing import List, Optional, AsyncGenerator
from llama_index.core import VectorStoreIndex
from llama_index.llms.openrouter import OpenRouter


logger = logging.getLogger(__name__)


class QueryEngine:
    """Движок для выполнения запросов"""

    def __init__(
        self,
        index: VectorStoreIndex,
        llm: OpenRouter,
        similarity_top_k: int = 3,
        max_retries: int = 20,
        retry_delay: float = 5.0,
    ):
        self.index = index
        self.llm = llm
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        logger.info(f"LLM модель: {self.llm}")
        logger.info(f"LLM модель: {self.llm.model}")
        logger.info(f"LLM модель: {self.llm.max_tokens}")
        logger.info(f"LLM модель: {self.llm.context_window}")
        logger.info(f"LLM модель: {self.llm.api_key}")

        # Создаем query engine
        self.query_engine = self.index.as_query_engine(
            streaming=True,
            similarity_top_k=similarity_top_k,
        )

    async def query(
        self,
        query: str,
        chat_history: Optional[List[dict]] = None,
        is_new_dialog: bool = True,
    ) -> AsyncGenerator[str, None]:
        """Выполнение запроса с повторными попытками"""
        attempt = 0
        last_error = None

        while attempt < self.max_retries:
            try:
                logger.info(
                    f"Начало выполнения запроса: {query} (попытка {attempt + 1}/{self.max_retries})"
                )
                logger.info(
                    f"Параметры LLM: model={self.llm.model}, max_tokens={self.llm.max_tokens}, context_window={self.llm.context_window}"
                )

                # Используем query engine для получения ответа
                response = await self.query_engine.aquery(query)

                async for chunk in response.response_gen:
                    yield chunk
                return  # Успешное выполнение, выходим из цикла

            except Exception as e:
                last_error = e
                attempt += 1
                logger.error(
                    f"Ошибка при выполнении запроса (попытка {attempt}/{self.max_retries}): {str(e)}"
                )
                logger.error(f"Тип ошибки: {type(e).__name__}")
                logger.error(
                    f"Детали ошибки: {e.__dict__ if hasattr(e, '__dict__') else 'Нет дополнительных деталей'}"
                )

                if attempt < self.max_retries:
                    logger.info(
                        f"Ожидание {self.retry_delay} секунд перед следующей попыткой..."
                    )
                    await asyncio.sleep(self.retry_delay)
                else:
                    logger.error(
                        f"Все попытки исчерпаны. Последняя ошибка: {str(last_error)}"
                    )
                    yield "Произошла ошибка при обработке запроса после нескольких попыток. Пожалуйста, попробуйте позже."

    async def check_llm_availability(self) -> bool:
        """Проверка доступности LLM"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.llm.base_url}/v1/models") as response:
                    return response.status == 200
        except Exception:
            return False
