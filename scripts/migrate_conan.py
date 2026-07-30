import sqlite3
from pathlib import Path

DB_PATH = Path("workspace/board.db")

MAPPING = {
    "jarvis": "conan",
    "stark": "kid",
    "banner": "agasa",
    "hawkeye": "heiji",
    "pepper": "haibara",
}

def migrate():
    if not DB_PATH.exists():
        print(f"No DB found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    print("Migrating tasks table...")
    for old_key, new_key in MAPPING.items():
        c.execute("UPDATE tasks SET assignee = ? WHERE assignee = ?", (new_key, old_key))
        c.execute("UPDATE tasks SET created_by = ? WHERE created_by = ?", (new_key, old_key))

    print("Migrating events table...")
    for old_key, new_key in MAPPING.items():
        c.execute("UPDATE events SET agent = ? WHERE agent = ?", (new_key, old_key))

    print("Migrating chat table...")
    for old_key, new_key in MAPPING.items():
        c.execute("UPDATE chat SET role = ? WHERE role = ?", (new_key, old_key))

    conn.commit()
    conn.close()
    print("Migration complete successfully!")

if __name__ == "__main__":
    migrate()
