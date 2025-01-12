import pytest
import os
import sys

def main():
    # Добавляем текущую директорию в PYTHONPATH
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    
    # Запускаем тесты
    pytest.main(["-v", "tests"])

if __name__ == "__main__":
    main() 