import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "mcp_logger.db"

WORKOUT_TABLES_SQL = [
    """
    CREATE TABLE IF NOT EXISTS workouts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date_time TEXT NOT NULL,
        workout_type TEXT,
        tags TEXT,
        notes TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS exercises (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workout_id INTEGER NOT NULL,
        order_index INTEGER NOT NULL,
        name TEXT NOT NULL,
        category TEXT,
        notes TEXT,
        FOREIGN KEY(workout_id) REFERENCES workouts(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        exercise_id INTEGER NOT NULL,
        set_index INTEGER NOT NULL,
        reps REAL,
        weight_kg REAL,
        weight_lbs REAL,
        distance_m REAL,
        distance_yards REAL,
        duration_s REAL,
        side TEXT CHECK(side IN ('left', 'right', 'both')),
        rpe REAL,
        rir REAL,
        is_warmup INTEGER DEFAULT 0,
        FOREIGN KEY(exercise_id) REFERENCES exercises(id) ON DELETE CASCADE
    )
    """,
]

NUTRITION_TABLES_SQL = [
    """
    CREATE TABLE IF NOT EXISTS nutrition_days (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL UNIQUE,
        notes TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS meals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        day_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        order_index INTEGER DEFAULT 0,
        FOREIGN KEY(day_id) REFERENCES nutrition_days(id) ON DELETE CASCADE,
        UNIQUE(day_id, name)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS meal_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        meal_id INTEGER NOT NULL,
        food_id TEXT NOT NULL,
        food_name TEXT NOT NULL,
        brand_name TEXT,
        serving_quantity REAL NOT NULL,
        serving_unit TEXT NOT NULL,
        grams REAL,
        calories REAL NOT NULL,
        protein_g REAL NOT NULL,
        carbs_g REAL NOT NULL,
        fats_g REAL NOT NULL,
        fiber_g REAL NOT NULL,
        notes TEXT,
        FOREIGN KEY(meal_id) REFERENCES meals(id) ON DELETE CASCADE
    )
    """,
]

BODY_TABLES_SQL = [
    """
    CREATE TABLE IF NOT EXISTS body_metrics (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL UNIQUE,
        body_weight_kg REAL,
        notes TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS skinfolds (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        body_metrics_id INTEGER NOT NULL,
        site_name TEXT NOT NULL,
        mm REAL NOT NULL,
        FOREIGN KEY(body_metrics_id) REFERENCES body_metrics(id) ON DELETE CASCADE
    )
    """,
]

SEARCH_TABLES_SQL = [
    """
    CREATE INDEX IF NOT EXISTS idx_workouts_date_time ON workouts (date_time);
    """,
]


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # Enable foreign key constraints
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _initialize_tables():
    conn = get_connection()
    cursor = conn.cursor()

    for statement in (*WORKOUT_TABLES_SQL, *NUTRITION_TABLES_SQL, *BODY_TABLES_SQL, *SEARCH_TABLES_SQL):
        cursor.execute(statement)

    conn.commit()
    conn.close()


_initialize_tables()


def serialize_tags(tags: list[str] | None) -> str | None:
    if tags is None:
        return None
    return json.dumps(tags)


def deserialize_tags(text: str | None) -> list[str]:
    if not text:
        return []
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return []

