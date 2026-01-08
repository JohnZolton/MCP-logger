# MCP Logger

A Python/`uv` + FastMCP server for logging workouts, nutrition, and body metrics. Single-user local SQLite database with stdio MCP interface.

## Features

- **Workouts**: Flexible `workout -> exercises[] -> sets[]` structure with tags, notes, RPE/RIR, distances, unilateral sides, etc.
- **Nutrition**: Cronometer/MyFitnessPal-style logging with meals and OpenNutrition-backed food snapshots.
- **Body Metrics**: Weight and customizable skinfold tracking.
- **Search**: Cross-domain search across all data.

## Tools

### Workout Tools

- `log_workout` - Log a complete workout with exercises and sets
- `get_workouts` - Query workouts with filters (date range, type, tag)
- `get_last_workout` - Get most recent workout by type or tag
- `get_exercise_history` - Get history for a specific exercise

### Nutrition Tools

- `upsert_nutrition_day` - Create/update a nutrition day
- `upsert_meal` - Create/update a meal within a day
- `add_or_update_meal_item` - Add/update food item (use with OpenNutrition MCP)
- `get_nutrition_day` - Get complete day with meals, items, and totals
- `get_nutrition_days_summary` - Get summaries for a date range
- `delete_meal_item`, `delete_meal`, `delete_nutrition_day` - Delete operations

### Body Metrics Tools

- `log_body_metrics` - Log weight and skinfolds
- `get_body_metrics` - Get body metrics with skinfolds

### Search

- `search_logs` - Search across workouts, nutrition, and body data

## Installation & Running

```bash
# Install dependencies
uv pip install -e .

# Run the MCP server (stdio interface)
uv run python -m src.main
```

## MCP Config Example

Add to your MCP configuration:

```json
{
  "mcpServers": {
    "logger": {
      "command": "uv",
      "args": ["run", "python", "-m", "src.main"],
      "cwd": "/path/to/mcp-logger"
    }
  }
}
```

## Nutrition Workflow with OpenNutrition MCP

1. AI uses OpenNutrition MCP to search for foods (`search-food-by-name`, `get-food-by-id`)
2. AI computes macros for the desired serving size
3. AI calls `add_or_update_meal_item` with food_id and calculated macros

## Workout Planning

The AI can call `get_last_workout` or `get_exercise_history` to retrieve past sessions, then generate suggested workouts. Progression logic lives in the client AI, not this server.

## Database

Data is stored in `mcp_logger.db` (SQLite) in the project root.

## Example Usage

### Log a Workout with Exercises

```json
{
  "date_time": "2026-01-06T18:30:00",
  "workout_type": "Strength",
  "tags": ["olympic", "speed"],
  "notes": "Great session",
  "exercises": [
    {
      "name": "Power Clean",
      "category": "Olympic Lift",
      "notes": "From blocks",
      "sets": [
        { "reps": 3, "weight_lbs": 185 },
        { "reps": 2, "weight_lbs": 195 },
        { "reps": 1, "weight_lbs": 205 }
      ]
    },
    {
      "name": "Sprint Starts",
      "category": "Sprint",
      "notes": "3 point stance",
      "sets": [{ "reps": 6, "distance_yards": 20 }]
    },
    {
      "name": "Single Leg Box Jumps",
      "category": "Plyometric",
      "notes": "5 sets of 2 each leg",
      "sets": [{ "reps": 10, "side": "both" }]
    }
  ]
}
```

### Set Fields

Each set can include:

- `reps`: Number of repetitions (int or float)
- `weight_kg` / `weight_lbs`: Weight in kg or lbs
- `distance_m` / `distance_yards`: Distance for running/rowing
- `duration_s`: Duration in seconds
- `side`: "left", "right", or "both" (for unilateral exercises)
- `rpe`: Rate of Perceived Exertion (1-10)
- `rir`: Reps In Reserve (0-5)
- `is_warmup`: Boolean for warmup sets
- `set_index`: Manual set ordering (defaults to order inserted)

### Log Body Metrics

```json
{
  "date": "2026-01-06",
  "body_weight_kg": 85.5,
  "skinfolds": {
    "chest": 12,
    "abdomen": 18,
    "thigh": 15,
    "tricep": 10,
    "subscapular": 14,
    "suprailiac": 16,
    "midaxillary": 11
  },
  "notes": "Morning measurement"
}
```
# MCP-logger
