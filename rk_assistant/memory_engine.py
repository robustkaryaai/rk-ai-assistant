"""
Simple Long-Term Memory Engine for RK AI.
Uses SQLite to store and retrieve user facts.
"""
import sqlite3
import time
from pathlib import Path
from typing import List, Dict, Any

from .config import DATA_DIR

MEMORY_DB = DATA_DIR / "memory.db"

def init_db():
    conn = sqlite3.connect(MEMORY_DB)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS memories
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  text TEXT,
                  tags TEXT,
                  timestamp REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS chats
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_message TEXT,
                  ai_message TEXT,
                  timestamp REAL)''')
    conn.commit()
    conn.close()

def store_chat(user_msg: str, ai_msg: str) -> None:
    """Store a chat turn in local history."""
    init_db()
    conn = sqlite3.connect(MEMORY_DB)
    c = conn.cursor()
    c.execute("INSERT INTO chats (user_message, ai_message, timestamp) VALUES (?, ?, ?)",
              (user_msg, ai_msg, time.time()))
    conn.commit()
    conn.close()
    print(f"[memory] Chat stored locally")

def get_recent_chats(limit: int = 10) -> List[Dict[str, str]]:
    """Retrieve the most recent chat turns."""
    if not MEMORY_DB.exists():
        return []
    init_db()
    conn = sqlite3.connect(MEMORY_DB)
    c = conn.cursor()
    c.execute("SELECT user_message, ai_message FROM chats ORDER BY timestamp DESC LIMIT ?", (limit,))
    results = [{"user": row[0], "ai": row[1]} for row in c.fetchall()]
    conn.close()
    # Reverse to get chronological order
    return results[::-1]

def store_memory(text: str, tags: str = "general") -> None:
    """Store a new memory."""
    from .config import MEMORY_ENABLED
    from . import settings_sync
    
    # Check both local config AND synced Appwrite setting
    if not MEMORY_ENABLED or not settings_sync.is_memory_enabled():
        print(f"[memory] Skipped storing (Disabled): '{text}'")
        return

    init_db() # Ensure table exists
    conn = sqlite3.connect(MEMORY_DB)
    c = conn.cursor()
    c.execute("INSERT INTO memories (text, tags, timestamp) VALUES (?, ?, ?)",
              (text, tags, time.time()))
    conn.commit()
    conn.close()
    print(f"[memory] Stored: '{text}'")

def retrieve_memories(query: str, limit: int = 5) -> List[str]:
    """
    Retrieve relevant memories based on simple keyword matching.
    For a 'Lite' RAG, we just return recent/relevant text.
    In future, we could add vector embeddings here.
    """
    if not MEMORY_DB.exists():
        return []

    conn = sqlite3.connect(MEMORY_DB)
    c = conn.cursor()
    
    # Simple keyword search (naive RAG)
    # Split query into words and look for matches
    keywords = [w for w in query.lower().split() if len(w) > 3]
    
    if not keywords:
        # If no keywords, return most recent
        c.execute("SELECT text FROM memories ORDER BY timestamp DESC LIMIT ?", (limit,))
    else:
        # Build a dynamic query: text LIKE '%word1%' OR text LIKE '%word2%'
        conditions = " OR ".join(["text LIKE ?"] * len(keywords))
        params = [f"%{w}%" for w in keywords]
        c.execute(f"SELECT text FROM memories WHERE {conditions} ORDER BY timestamp DESC LIMIT ?", (*params, limit))
        
    results = [row[0] for row in c.fetchall()]
    conn.close()
    return results

def get_all_memories(limit: int = 10) -> List[str]:
    """Return the most recent memories."""
    if not MEMORY_DB.exists():
        return []
    conn = sqlite3.connect(MEMORY_DB)
    c = conn.cursor()
    c.execute("SELECT text FROM memories ORDER BY timestamp DESC LIMIT ?", (limit,))
    results = [row[0] for row in c.fetchall()]
    conn.close()
    return results
