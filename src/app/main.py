from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.api import api_router
from app.core.config import settings
from app.core.database import init_db
from app.core.middleware import error_handler_middleware

# Инициализируем базу данных
init_db()

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
)

# Настройка CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Добавляем middleware для обработки ошибок
app.middleware("http")(error_handler_middleware)

# Подключаем роутеры
app.include_router(api_router, prefix=settings.API_V1_STR)


# Добавляем обработчик для корневого пути
@app.get("/")
async def root():
    return {"message": "Добро пожаловать в API управления документами"}
