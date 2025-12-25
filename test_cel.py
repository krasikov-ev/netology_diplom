# test_fix.py
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'orders.settings')

try:
    import orders.settings
    print("✓ Успешно импортирован orders.settings")
    print(f"Путь: {orders.settings.__file__}")
except Exception as e:
    print(f"✗ Ошибка: {e}")