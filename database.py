import sqlite3
import logging
import random
from datetime import datetime, timedelta

DB_PATH = "users.db"

def init_db():
    """Створює таблицю users, якщо її немає."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                email TEXT,
                is_verified INTEGER DEFAULT 0,
                verification_code TEXT,
                code_expires_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        logging.info("✅ База даних ініціалізована")

def generate_code(length: int = 6) -> str:
    """Генерує випадковий 6-значний код."""
    return ''.join(random.choices('0123456789', k=length))

def save_user_email(user_id: int, email: str) -> str:
    """Зберігає email і генерує код верифікації."""
    code = generate_code()
    expires_at = datetime.now() + timedelta(minutes=5)
    
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO users (user_id, email, verification_code, code_expires_at, is_verified)
            VALUES (?, ?, ?, ?, 0)
            ON CONFLICT(user_id) DO UPDATE SET
                email = excluded.email,
                verification_code = excluded.verification_code,
                code_expires_at = excluded.code_expires_at,
                is_verified = 0
        """, (user_id, email, code, expires_at))
        conn.commit()
        logging.info(f"📧 Email збережено для {user_id}: {email}")
        return code

def verify_code(user_id: int, code: str) -> bool:
    """Перевіряє код верифікації. Повертає True, якщо код правильний і не прострочений."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT verification_code, code_expires_at, is_verified
            FROM users WHERE user_id = ?
        """, (user_id,))
        result = cursor.fetchone()
        
        if not result:
            return False
        
        stored_code, expires_at, is_verified = result
        
        if is_verified:
            return True
        
        if datetime.now() > datetime.fromisoformat(expires_at):
            return False
        
        if stored_code == code:
            cursor.execute("UPDATE users SET is_verified = 1 WHERE user_id = ?", (user_id,))
            conn.commit()
            return True
        
        return False

def get_user_email(user_id: int) -> str | None:
    """Повертає email користувача (тільки якщо підтверджено)."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT email FROM users WHERE user_id = ? AND is_verified = 1", (user_id,))
        result = cursor.fetchone()
        return result[0] if result else None

def is_user_verified(user_id: int) -> bool:
    """Перевіряє, чи підтверджено email."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT is_verified FROM users WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        return result[0] == 1 if result else False

def get_user_data(user_id: int) -> dict | None:
    """Повертає всі дані користувача."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT email, is_verified FROM users WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        if result:
            return {"email": result[0], "is_verified": result[1]}
        return None

def delete_user(user_id: int):
    """Видаляє користувача з БД."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        conn.commit()
        logging.info(f"🗑️ Користувача {user_id} видалено")