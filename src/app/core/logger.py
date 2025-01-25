import logging
import sys
from typing import List
from loguru import logger
import json

class InterceptHandler(logging.Handler):
    def emit(self, record):
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame, depth = logging.currentframe(), 2
        while frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )

def setup_logging():
    # Удаляем все существующие обработчики
    logging.root.handlers = []
    
    # Настройка перехватчика для стандартных логов Python
    logging.root.addHandler(InterceptHandler())
    
    # Устанавливаем уровень логирования
    logging.root.setLevel(logging.INFO)
    
    # Отключаем логи от uvicorn.access
    for name in logging.root.manager.loggerDict.keys():
        if name.startswith("uvicorn."):
            logging.getLogger(name).handlers = []
    
    # Настройка логов
    logger.configure(
        handlers=[
            {
                "sink": sys.stdout,
                "format": "{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
                "level": "INFO",
            },
            {
                "sink": "logs/app.log",
                "format": "{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
                "level": "INFO",
                "rotation": "1 day",
                "retention": "1 month",
            },
        ]
    ) 