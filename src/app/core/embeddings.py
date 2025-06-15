import aiohttp
from typing import List
from llama_index.core.embeddings import BaseEmbedding


class CustomEmbedding(BaseEmbedding):
    """Кастомная модель эмбеддингов"""

    def __init__(self, api_url: str):
        super().__init__()
        self.__dict__["_api_url"] = api_url

    async def _get_text_embedding(self, text: str) -> List[float]:
        """Асинхронная версия метода для получения эмбеддинга текста"""
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self._api_url}/embeddings", json={"texts": [text]}
            ) as response:
                data = await response.json()
                return data["embeddings"][0]

    async def _aget_query_embedding(self, query: str) -> List[float]:
        """Асинхронная версия метода для получения эмбеддинга запроса"""
        return await self._get_text_embedding(query)

    async def _get_query_embedding(self, query: str) -> List[float]:
        """Асинхронная версия метода для получения эмбеддинга запроса"""
        return await self._get_text_embedding(query)

    def _get_text_embedding_sync(self, text: str) -> List[float]:
        """Синхронная версия для обратной совместимости"""
        import nest_asyncio
        import asyncio

        # Позволяет запускать event loop внутри другого event loop
        nest_asyncio.apply()

        # Получаем текущий event loop или создаем новый
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(self._get_text_embedding(text))

    def _get_query_embedding_sync(self, query: str) -> List[float]:
        """Синхронная версия для обратной совместимости"""
        return self._get_text_embedding_sync(query)
