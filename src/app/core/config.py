from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    PROJECT_NAME: str = "Document Management API"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"

    POSTGRES_SERVER: str = "localhost"
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgrespass"
    POSTGRES_DB: str = "doc_management"

    PGVECTOR_SERVER: str = "localhost"
    PGVECTOR_PORT: int = 5432
    PGVECTOR_USER: str = "pgvector"
    PGVECTOR_PASSWORD: str = "pgvectorpass"
    PGVECTOR_DB: str = "vectors"

    SECRET_KEY: str
    JWT_SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # Minio configuration
    MINIO_ROOT_USER: str
    MINIO_ROOT_PASSWORD: str
    MINIO_ENDPOINT: str
    MINIO_SECURE: bool = False
    MINIO_BUCKET_NAME: str = "documents"

    # OpenAI и Embedding settings
    MODEL_NAME: str
    API_KEY: str
    TEMPERATURE: float = 0.7
    MAX_TOKENS: int = 2048
    STREAM_TOKENS: bool = True

    EMBEDDING_BASE_URL: str

    class Config:
        env_file = ".env"


settings = Settings()
