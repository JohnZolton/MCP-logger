"""MCP Logger server using FastMCP stdio interface."""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from fastmcp import FastMCP

from .db import get_connection, serialize_tags, deserialize_tags

app = FastMCP("MCP Logger")


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def _ensure_iso_date(value: str) -> str:
    try:
        return datetime.fromisoformat(value).isoformat()
    except ValueError:
        raise ValueError(f"Invalid ISO datetime: {value}")


def _ensure_date(value: str) -> str:
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            parsed = datetime.strptime(value, fmt)
            return parsed.date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"Invalid date string: {value}")


def _load_sets(conn: sqlite3.Connection, exercise_id: int) -> list[dict[str, Any]]:
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM sets WHERE exercise_id = ? ORDER BY set_index", (exercise_id,))
    return [_row_to_dict(row) for row in cursor.fetchall()]


def _hydrate_workout(conn: sqlite3.Connection, workout: dict[str, Any]) -> dict[str, Any]:
    workout["tags"] = deserialize_tags(workout.get("tags"))
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM exercises WHERE workout_id = ? ORDER BY order_index",
        (workout["id"],),
    )
    exercises = []
    for ex_row in cursor.fetchall():
        ex = _row_to_dict(ex_row)
        ex["sets"] = _load_sets(conn, ex["id"])
        exercises.append(ex)
    workout["exercises"] = exercises
    return workout


# ============================================================
# Workout Tools
# ============================================================


def _parse_json_array(value: Any) -> Any:
    """Parse a JSON string into an array, or return the original value if not a string."""
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass
    return value


@app.tool()
def log_workout(
    date_time: str,
    workout_type: Optional[str] = None,
    tags: Optional[Any] = None,
    notes: Optional[str] = None,
    exercises: Optional[Any] = None,
) -> dict[str, Any]:
    """Log a complete workout with exercises and sets.

    Returns the fully logged workout with all exercises and sets for confirmation.

    Args:
        date_time: ISO datetime string (e.g., "2026-01-06T18:30:00")
        workout_type: Optional type/category for the workout
        tags: Optional list of tags (e.g., ["legs", "sprint"])
        notes: Optional notes for the workout
        exercises: List of exercises with sets. Each exercise should have:
            - name: str (required)
            - category: Optional[str]
            - notes: Optional[str]
            - sets: List of sets with fields like reps, weight_kg, weight_lbs, distance_yards, side, etc.
    """
    # Handle JSON string inputs (for clients that serialize arrays as strings)
    tags = _parse_json_array(tags)
    exercises = _parse_json_array(exercises)
    
    # Validate types after parsing
    if tags is not None and not isinstance(tags, list):
        raise TypeError(f"tags must be a list, got {type(tags).__name__}")
    if exercises is not None and not isinstance(exercises, list):
        raise TypeError(f"exercises must be a list, got {type(exercises).__name__}")
    
    date_time = _ensure_iso_date(date_time)
    tags_json = serialize_tags(tags)

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO workouts (date_time, workout_type, tags, notes) VALUES (?, ?, ?, ?)",
        (date_time, workout_type, tags_json, notes),
    )
    workout_id = cursor.lastrowid

    if exercises:
        for order_index, exercise in enumerate(exercises, start=1):
            exercise_name = exercise.get("name")
            if not exercise_name:
                raise ValueError(f"Exercise at index {order_index} is missing required 'name' field")
            
            cursor.execute(
                "INSERT INTO exercises (workout_id, order_index, name, category, notes) VALUES (?, ?, ?, ?, ?)",
                (workout_id, order_index, exercise_name, exercise.get("category"), exercise.get("notes")),
            )
            exercise_id = cursor.lastrowid

            for set_index, set_payload in enumerate(exercise.get("sets", []), start=1):
                cursor.execute(
                    """INSERT INTO sets (
                        exercise_id, set_index, reps, weight_kg, weight_lbs,
                        distance_m, distance_yards, duration_s,
                        side, rpe, rir, is_warmup
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        exercise_id,
                        set_payload.get("set_index") or set_index,
                        set_payload.get("reps"),
                        set_payload.get("weight_kg"),
                        set_payload.get("weight_lbs"),
                        set_payload.get("distance_m"),
                        set_payload.get("distance_yards"),
                        set_payload.get("duration_s"),
                        set_payload.get("side"),
                        set_payload.get("rpe"),
                        set_payload.get("rir"),
                        1 if set_payload.get("is_warmup") else 0,
                    ),
                )

    conn.commit()
    
    # Return the fully hydrated workout for confirmation
    workout = cursor.execute("SELECT * FROM workouts WHERE id = ?", (workout_id,)).fetchone()
    result = _hydrate_workout(conn, _row_to_dict(workout))
    
    conn.close()
    return result


@app.tool()
def add_exercise(
    workout_id: int,
    name: str,
    category: Optional[str] = None,
    notes: Optional[str] = None,
) -> dict[str, int]:
    """Add an exercise to an existing workout.
    
    Args:
        workout_id: ID of the workout to add exercise to
        name: Name of the exercise
        category: Optional category (e.g., 'Squat', 'Push', 'Pull')
        notes: Optional notes about the exercise
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    # Get current max order_index
    cursor.execute("SELECT COALESCE(MAX(order_index), 0) FROM exercises WHERE workout_id = ?", (workout_id,))
    max_order = cursor.fetchone()[0]
    
    cursor.execute(
        "INSERT INTO exercises (workout_id, order_index, name, category, notes) VALUES (?, ?, ?, ?, ?)",
        (workout_id, max_order + 1, name, category, notes),
    )
    exercise_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return {"exercise_id": exercise_id}


@app.tool()
def add_set(
    exercise_id: int,
    reps: Optional[float] = None,
    weight_kg: Optional[float] = None,
    weight_lbs: Optional[float] = None,
    distance_m: Optional[float] = None,
    distance_yards: Optional[float] = None,
    duration_s: Optional[float] = None,
    side: Optional[str] = None,
    rpe: Optional[float] = None,
    rir: Optional[float] = None,
    is_warmup: bool = False,
) -> dict[str, int]:
    """Add a set to an existing exercise.
    
    Args:
        exercise_id: ID of the exercise to add set to
        reps: Number of repetitions
        weight_kg: Weight in kilograms
        weight_lbs: Weight in pounds
        distance_m: Distance in meters
        distance_yards: Distance in yards
        duration_s: Duration in seconds
        side: 'left', 'right', or 'both' for unilateral exercises
        rpe: Rate of Perceived Exertion (1-10)
        rir: Reps In Reserve (0-5)
        is_warmup: Whether this is a warmup set
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    # Get current max set_index
    cursor.execute("SELECT COALESCE(MAX(set_index), 0) FROM sets WHERE exercise_id = ?", (exercise_id,))
    max_set = cursor.fetchone()[0]
    
    cursor.execute(
        """INSERT INTO sets (
            exercise_id, set_index, reps, weight_kg, weight_lbs,
            distance_m, distance_yards, duration_s, side, rpe, rir, is_warmup
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            exercise_id, max_set + 1, reps, weight_kg, weight_lbs,
            distance_m, distance_yards, duration_s, side, rpe, rir, 1 if is_warmup else 0
        ),
    )
    set_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return {"set_id": set_id}


@app.tool()
def get_workouts(
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    workout_type: Optional[str] = None,
    tag: Optional[str] = None,
    exercise_name_contains: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, list[dict[str, Any]]]:
    """Query workouts with various filters."""
    conn = get_connection()
    cursor = conn.cursor()

    filters: list[str] = []
    params: list[Any] = []

    if from_date:
        filters.append("date_time >= ?")
        params.append(f"{_ensure_date(from_date)}T00:00:00")
    if to_date:
        filters.append("date_time <= ?")
        params.append(f"{_ensure_date(to_date)}T23:59:59")
    if workout_type:
        filters.append("workout_type = ?")
        params.append(workout_type)
    if tag:
        filters.append("tags LIKE ?")
        params.append(f'%"{tag}"%')

    base = "SELECT * FROM workouts"
    if filters:
        base += " WHERE " + " AND ".join(filters)
    base += " ORDER BY date_time DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    cursor.execute(base, params)
    rows = cursor.fetchall()

    workouts = [_hydrate_workout(conn, _row_to_dict(row)) for row in rows]
    conn.close()
    return {"workouts": workouts}


@app.tool()
def get_last_workout(
    workout_type: Optional[str] = None,
    tag: Optional[str] = None,
) -> dict[str, Any | None]:
    """Get the most recent workout matching type or tag."""
    if not workout_type and not tag:
        raise ValueError("At least one of workout_type or tag is required")

    conn = get_connection()
    cursor = conn.cursor()

    filters: list[str] = []
    params: list[Any] = []
    if workout_type:
        filters.append("workout_type = ?")
        params.append(workout_type)
    if tag:
        filters.append("tags LIKE ?")
        params.append(f'%"{tag}"%')

    base = "SELECT * FROM workouts"
    if filters:
        base += " WHERE " + " AND ".join(filters)
    base += " ORDER BY date_time DESC LIMIT 1"

    cursor.execute(base, params)
    row = cursor.fetchone()
    if not row:
        conn.close()
        return {"workout": None}

    workout = _hydrate_workout(conn, _row_to_dict(row))
    conn.close()
    return {"workout": workout}


@app.tool()
def get_exercise_history(
    exercise_name: str,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    limit: int = 20,
) -> dict[str, list[dict[str, Any]]]:
    """Get history of a specific exercise across workouts."""
    conn = get_connection()
    cursor = conn.cursor()

    base = """
    SELECT w.id as workout_id, w.date_time, w.workout_type, w.tags, w.notes as workout_notes,
           e.id as exercise_id, e.name as exercise_name, e.category as exercise_category, e.notes as exercise_notes
    FROM workouts w
    JOIN exercises e ON e.workout_id = w.id
    WHERE LOWER(e.name) = LOWER(?)
    """
    params: list[Any] = [exercise_name]

    if from_date:
        base += " AND w.date_time >= ?"
        params.append(f"{_ensure_date(from_date)}T00:00:00")
    if to_date:
        base += " AND w.date_time <= ?"
        params.append(f"{_ensure_date(to_date)}T23:59:59")

    base += " ORDER BY w.date_time DESC LIMIT ?"
    params.append(limit)

    cursor.execute(base, params)
    rows = cursor.fetchall()

    entries: list[dict[str, Any]] = []
    for row in rows:
        item = _row_to_dict(row)
        item["tags"] = deserialize_tags(item["tags"])
        item["sets"] = _load_sets(conn, item["exercise_id"])
        entries.append(item)

    conn.close()
    return {"entries": entries}


# ============================================================
# Nutrition Tools (Cronometer/MyFitnessPal style with meals)
# ============================================================


@app.tool()
def upsert_nutrition_day(date: str, notes: Optional[str] = None) -> dict[str, int]:
    """Create or update a nutrition day entry."""
    date = _ensure_date(date)
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO nutrition_days (date, notes) VALUES (?, ?) ON CONFLICT(date) DO UPDATE SET notes = ?",
        (date, notes, notes),
    )
    day_id = cursor.lastrowid or cursor.execute("SELECT id FROM nutrition_days WHERE date = ?", (date,)).fetchone()[0]
    conn.commit()
    conn.close()
    return {"day_id": day_id}


@app.tool()
def upsert_meal(date: str, name: str, order_index: int = 0) -> dict[str, int]:
    """Create or update a meal within a nutrition day."""
    date = _ensure_date(date)
    conn = get_connection()
    cursor = conn.cursor()

    # Ensure day exists
    cursor.execute("INSERT OR IGNORE INTO nutrition_days (date) VALUES (?)", (date,))
    cursor.execute("SELECT id FROM nutrition_days WHERE date = ?", (date,))
    day_id = cursor.fetchone()[0]

    # Upsert meal
    cursor.execute(
        """INSERT INTO meals (day_id, name, order_index) VALUES (?, ?, ?)
           ON CONFLICT(day_id, name) DO UPDATE SET order_index = ?""",
        (day_id, name, order_index, order_index),
    )
    meal_id = cursor.lastrowid or cursor.execute(
        "SELECT id FROM meals WHERE day_id = ? AND name = ?", (day_id, name)
    ).fetchone()[0]

    conn.commit()
    conn.close()
    return {"meal_id": meal_id}


@app.tool()
def add_or_update_meal_item(
    date: str,
    meal_name: str,
    food_id: str,
    food_name: str,
    serving_quantity: float,
    serving_unit: str,
    calories: float,
    protein_g: float,
    carbs_g: float,
    fats_g: float,
    fiber_g: float,
    brand_name: Optional[str] = None,
    grams: Optional[float] = None,
    notes: Optional[str] = None,
    item_id: Optional[int] = None,
) -> dict[str, int]:
    """Add or update a food item within a meal.

    The AI should first use OpenNutrition MCP to find food_id and get macros,
    then call this tool with the calculated values for the serving quantity.
    """
    date = _ensure_date(date)
    conn = get_connection()
    cursor = conn.cursor()

    # Ensure day and meal exist
    cursor.execute("INSERT OR IGNORE INTO nutrition_days (date) VALUES (?)", (date,))
    cursor.execute("SELECT id FROM nutrition_days WHERE date = ?", (date,))
    day_id = cursor.fetchone()[0]

    cursor.execute(
        "INSERT OR IGNORE INTO meals (day_id, name, order_index) VALUES (?, ?, 0)",
        (day_id, meal_name),
    )
    cursor.execute("SELECT id FROM meals WHERE day_id = ? AND name = ?", (day_id, meal_name))
    meal_id = cursor.fetchone()[0]

    if item_id:
        # Update existing item
        cursor.execute(
            """UPDATE meal_items SET
               food_id=?, food_name=?, brand_name=?, serving_quantity=?, serving_unit=?,
               grams=?, calories=?, protein_g=?, carbs_g=?, fats_g=?, fiber_g=?, notes=?
               WHERE id=?""",
            (
                food_id, food_name, brand_name, serving_quantity, serving_unit,
                grams, calories, protein_g, carbs_g, fats_g, fiber_g, notes, item_id,
            ),
        )
    else:
        # Insert new item
        cursor.execute(
            """INSERT INTO meal_items (
               meal_id, food_id, food_name, brand_name, serving_quantity, serving_unit,
               grams, calories, protein_g, carbs_g, fats_g, fiber_g, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                meal_id, food_id, food_name, brand_name, serving_quantity, serving_unit,
                grams, calories, protein_g, carbs_g, fats_g, fiber_g, notes,
            ),
        )
        item_id = cursor.lastrowid

    conn.commit()
    conn.close()
    return {"item_id": item_id, "meal_id": meal_id, "day_id": day_id}


@app.tool()
def get_nutrition_day(date: str) -> dict[str, Any | None]:
    """Get a complete nutrition day with meals and items."""
    date = _ensure_date(date)
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM nutrition_days WHERE date = ?", (date,))
    day_row = cursor.fetchone()
    if not day_row:
        conn.close()
        return {"day": None}

    day = _row_to_dict(day_row)
    cursor.execute("SELECT * FROM meals WHERE day_id = ? ORDER BY order_index", (day["id"],))

    meals = []
    for meal_row in cursor.fetchall():
        meal = _row_to_dict(meal_row)
        cursor.execute("SELECT * FROM meal_items WHERE meal_id = ?", (meal["id"],))
        items = [_row_to_dict(r) for r in cursor.fetchall()]

        # Compute totals
        totals = {
            "calories": sum(i["calories"] for i in items),
            "protein_g": sum(i["protein_g"] for i in items),
            "carbs_g": sum(i["carbs_g"] for i in items),
            "fats_g": sum(i["fats_g"] for i in items),
            "fiber_g": sum(i["fiber_g"] for i in items),
        }
        meal["items"] = items
        meal["totals"] = totals
        meals.append(meal)

    # Compute day totals
    day["totals"] = {
        "calories": sum(m["totals"]["calories"] for m in meals),
        "protein_g": sum(m["totals"]["protein_g"] for m in meals),
        "carbs_g": sum(m["totals"]["carbs_g"] for m in meals),
        "fats_g": sum(m["totals"]["fats_g"] for m in meals),
        "fiber_g": sum(m["totals"]["fiber_g"] for m in meals),
    }
    day["meals"] = meals
    conn.close()
    return {"day": day}


@app.tool()
def get_nutrition_days_summary(
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    limit: int = 31,
    offset: int = 0,
) -> dict[str, list[dict[str, Any]]]:
    """Get nutrition summaries for a date range."""
    conn = get_connection()
    cursor = conn.cursor()

    filters = []
    params = []
    if from_date:
        filters.append("date >= ?")
        params.append(_ensure_date(from_date))
    if to_date:
        filters.append("date <= ?")
        params.append(_ensure_date(to_date))

    base = "SELECT * FROM nutrition_days"
    if filters:
        base += " WHERE " + " AND ".join(filters)
    base += " ORDER BY date DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    cursor.execute(base, params)
    days = []
    for row in cursor.fetchall():
        day = _row_to_dict(row)
        cursor.execute("SELECT * FROM meals WHERE day_id = ?", (day["id"],))
        meals = cursor.fetchall()
        items = []
        for m in meals:
            cursor.execute("SELECT * FROM meal_items WHERE meal_id = ?", (m["id"],))
            items.extend(cursor.fetchall())
        day["totals"] = {
            "calories": sum(i["calories"] for i in items) if items else 0,
            "protein_g": sum(i["protein_g"] for i in items) if items else 0,
            "carbs_g": sum(i["carbs_g"] for i in items) if items else 0,
            "fats_g": sum(i["fats_g"] for i in items) if items else 0,
            "fiber_g": sum(i["fiber_g"] for i in items) if items else 0,
        }
        days.append(day)

    conn.close()
    return {"days": days}


@app.tool()
def delete_meal_item(item_id: int) -> dict[str, bool]:
    """Delete a meal item."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM meal_items WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()
    return {"deleted": cursor.rowcount > 0}


@app.tool()
def delete_meal(meal_id: int, delete_items: bool = True) -> dict[str, bool]:
    """Delete a meal and optionally its items."""
    conn = get_connection()
    cursor = conn.cursor()
    if delete_items:
        cursor.execute("DELETE FROM meal_items WHERE meal_id = ?", (meal_id,))
    cursor.execute("DELETE FROM meals WHERE id = ?", (meal_id,))
    conn.commit()
    conn.close()
    return {"deleted": cursor.rowcount > 0}


@app.tool()
def delete_nutrition_day(date: str, cascade: bool = True) -> dict[str, bool]:
    """Delete a nutrition day and optionally cascade to meals/items."""
    date = _ensure_date(date)
    conn = get_connection()
    cursor = conn.cursor()
    if cascade:
        # Get meal IDs first
        cursor.execute("SELECT id FROM meals WHERE day_id IN (SELECT id FROM nutrition_days WHERE date = ?)", (date,))
        meal_ids = [r[0] for r in cursor.fetchall()]
        if meal_ids:
            placeholders = ",".join("?" * len(meal_ids))
            cursor.execute(f"DELETE FROM meal_items WHERE meal_id IN ({placeholders})", meal_ids)
        cursor.execute("DELETE FROM meals WHERE day_id IN (SELECT id FROM nutrition_days WHERE date = ?)", (date,))
    cursor.execute("DELETE FROM nutrition_days WHERE date = ?", (date,))
    conn.commit()
    conn.close()
    return {"deleted": cursor.rowcount > 0}


# ============================================================
# Body Metrics Tools
# ============================================================


@app.tool()
def log_body_metrics(
    date: str,
    body_weight_kg: Optional[float] = None,
    skinfolds: Optional[dict[str, float]] = None,
    notes: Optional[str] = None,
) -> dict[str, int]:
    """Log body weight and skinfold measurements.
    
    Args:
        date: Date in YYYY-MM-DD format
        body_weight_kg: Body weight in kilograms (optional)
        skinfolds: Dictionary of skinfold measurements in mm (optional).
                   Can be a single site like {"abdomen": 10} or multiple sites
                   like {"chest": 12, "abdomen": 18, "thigh": 15}.
                   Common sites: abdomen, chest, thigh, tricep, subscapular, 
                   suprailiac, midaxillary
        notes: Optional notes about the measurement
    
    Example:
        Single belly skinfold: {"abdomen": 10}
        Multiple sites: {"chest": 12, "abdomen": 18, "thigh": 15}
    """
    date = _ensure_date(date)
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "INSERT INTO body_metrics (date, body_weight_kg, notes) VALUES (?, ?, ?)",
        (date, body_weight_kg, notes),
    )
    metrics_id = cursor.lastrowid

    if skinfolds:
        for site, mm in skinfolds.items():
            cursor.execute(
                "INSERT INTO skinfolds (body_metrics_id, site_name, mm) VALUES (?, ?, ?)",
                (metrics_id, site, mm),
            )

    conn.commit()
    conn.close()
    return {"body_metrics_id": metrics_id}


@app.tool()
def get_body_metrics(
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    limit: int = 31,
    offset: int = 0,
) -> dict[str, list[dict[str, Any]]]:
    """Get body metrics with skinfolds."""
    conn = get_connection()
    cursor = conn.cursor()

    filters = []
    params = []
    if from_date:
        filters.append("date >= ?")
        params.append(_ensure_date(from_date))
    if to_date:
        filters.append("date <= ?")
        params.append(_ensure_date(to_date))

    base = "SELECT * FROM body_metrics"
    if filters:
        base += " WHERE " + " AND ".join(filters)
    base += " ORDER BY date DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    cursor.execute(base, params)
    metrics_list = []
    for row in cursor.fetchall():
        metrics = _row_to_dict(row)
        cursor.execute("SELECT site_name, mm FROM skinfolds WHERE body_metrics_id = ?", (metrics["id"],))
        skinfolds = {r["site_name"]: r["mm"] for r in cursor.fetchall()}
        metrics["skinfolds"] = skinfolds
        metrics_list.append(metrics)

    conn.close()
    return {"metrics": metrics_list}


# ============================================================
# Search Tool
# ============================================================


@app.tool()
def search_logs(
    query: str,
    domains: Optional[list[str]] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    limit: int = 20,
) -> dict[str, list[dict[str, Any]]]:
    """Search across workouts, nutrition days, and body metrics."""
    domains = domains or ["workout", "nutrition", "body"]
    results = []

    conn = get_connection()
    cursor = conn.cursor()

    if "workout" in domains:
        filters = ["(notes LIKE ? OR workout_type LIKE ? OR tags LIKE ?)"]
        params = [f"%{query}%", f"%{query}%", f"%{query}%"]
        if from_date:
            filters.append("date_time >= ?")
            params.append(f"{_ensure_date(from_date)}T00:00:00")
        if to_date:
            filters.append("date_time <= ?")
            params.append(f"{_ensure_date(to_date)}T23:59:59")
        base = "SELECT * FROM workouts WHERE " + " AND ".join(filters) + " LIMIT ?"
        params.append(limit)
        cursor.execute(base, params)
        for row in cursor.fetchall():
            workout = _hydrate_workout(conn, _row_to_dict(row))
            results.append({"domain": "workout", "workout": workout})

    if len(results) >= limit:
        conn.close()
        return {"results": results[:limit]}

    remaining = limit - len(results)

    if "nutrition" in domains:
        filters = ["(notes LIKE ?)"]
        params = [f"%{query}%"]
        if from_date:
            filters.append("date >= ?")
            params.append(_ensure_date(from_date))
        if to_date:
            filters.append("date <= ?")
            params.append(_ensure_date(to_date))
        base = "SELECT * FROM nutrition_days WHERE " + " AND ".join(filters) + " LIMIT ?"
        params.append(remaining)
        cursor.execute(base, params)
        for row in cursor.fetchall():
            results.append({"domain": "nutrition", "nutrition": _row_to_dict(row)})

    if len(results) >= limit:
        conn.close()
        return {"results": results[:limit]}

    remaining = limit - len(results)

    if "body" in domains:
        filters = ["(notes LIKE ?)"]
        params = [f"%{query}%"]
        if from_date:
            filters.append("date >= ?")
            params.append(_ensure_date(from_date))
        if to_date:
            filters.append("date <= ?")
            params.append(_ensure_date(to_date))
        base = "SELECT * FROM body_metrics WHERE " + " AND ".join(filters) + " LIMIT ?"
        params.append(remaining)
        cursor.execute(base, params)
        for row in cursor.fetchall():
            results.append({"domain": "body", "body": _row_to_dict(row)})

    conn.close()
    return {"results": results}


if __name__ == "__main__":
    app.run()
