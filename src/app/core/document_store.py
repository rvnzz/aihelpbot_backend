import logging
from typing import List
from llama_index.core.schema import TextNode
from llama_index.vector_stores.postgres import PGVectorStore
from llama_index.core.node_parser import SentenceSplitter

logger = logging.getLogger(__name__)


class DocumentStore:
    """Управление документами в векторном хранилище"""

    def __init__(self, vector_store: PGVectorStore, config):
        self.vector_store = vector_store
        self.config = config
        self.text_splitter = SentenceSplitter(
            chunk_size=config.chunk_size, chunk_overlap=config.chunk_overlap
        )

    async def index_document(self, document_id: int, content: str) -> None:
        """Индексация документа"""
        nodes = self._create_document_nodes(document_id, content)
        self.vector_store.add(nodes)

    def _create_document_nodes(self, document_id: int, content: str) -> List[TextNode]:
        """Создание узлов документа"""
        # Разбиваем текст на чанки
        text_chunks = self.text_splitter.split_text(content)

        # Создаем узлы для каждого чанка
        nodes = []
        for i, chunk in enumerate(text_chunks):
            node = TextNode(
                text=chunk,
                metadata={
                    "document_id": document_id,
                    "chunk_index": i,
                },
            )
            nodes.append(node)

        return nodes

    async def check_availability(self) -> bool:
        """Проверка доступности хранилища"""
        try:
            # Простой запрос для проверки соединения
            return bool(self.vector_store.client.query("SELECT 1").fetchone())
        except Exception:
            return False
