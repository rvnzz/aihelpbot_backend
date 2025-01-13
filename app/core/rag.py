from typing import Optional

from llama_index import Document, ServiceContext, VectorStoreIndex
from llama_index.embeddings import HuggingFaceEmbedding
from llama_index.llms import OpenAILike


class RAGManager:
    def __init__(self, model_url: str, model_name: str):
        self.llm = OpenAILike(
            model=model_name,
            api_base=model_url,
            api_key="not-needed",
            is_chat_model=True,
            temperature=0.7,
        )

        self.embed_model = HuggingFaceEmbedding(
            model_name="ai-forever/sbert_large_nlu_ru"
        )

        self.service_context = ServiceContext.from_defaults(
            llm=self.llm, embed_model=self.embed_model
        )

        self.indices = {}  # document_id -> Index

    async def create_index_for_document(self, document_id: int, content: str) -> None:
        """Создает индекс для документа"""
        documents = [Document(text=content)]
        index = VectorStoreIndex.from_documents(
            documents, service_context=self.service_context
        )
        self.indices[document_id] = index

    async def query_document(self, document_id: int, query: str) -> Optional[str]:
        """Выполняет запрос к документу"""
        if document_id not in self.indices:
            return None

        query_engine = self.indices[document_id].as_query_engine()
        response = query_engine.query(query)
        return str(response)

    def remove_index(self, document_id: int) -> None:
        """Удаляет индекс документа"""
        if document_id in self.indices:
            del self.indices[document_id]
