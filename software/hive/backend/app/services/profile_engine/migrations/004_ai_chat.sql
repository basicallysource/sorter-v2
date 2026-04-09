CREATE TABLE IF NOT EXISTS ai_chats (
    id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    pydantic_messages TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ai_chat_messages (
    id TEXT PRIMARY KEY,
    chat_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    proposed_rule TEXT,
    accepted INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY (chat_id) REFERENCES ai_chats(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_ai_chats_profile_rule ON ai_chats(profile_id, rule_id);
CREATE INDEX IF NOT EXISTS idx_ai_chat_messages_chat ON ai_chat_messages(chat_id);
