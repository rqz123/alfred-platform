import json
import os
from datetime import datetime, timezone

import pytz
from croniter import croniter
from openai import AsyncOpenAI

_client: AsyncOpenAI | None = None


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    return _client


REMINDER_SCHEMA = {
    "name": "parse_reminder",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "body": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "type": {"type": "string", "enum": ["once", "recurring", "event"]},
            "fireAt": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "cronExpression": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "confidence": {"type": "number"},
            "rawInterpretation": {"type": "string"},
        },
        "required": [
            "title", "body", "type", "fireAt",
            "cronExpression", "confidence", "rawInterpretation",
        ],
        "additionalProperties": False,
    },
}


def compute_next_fire(cron_expr: str, tz_name: str) -> str | None:
    try:
        tz = pytz.timezone(tz_name)
        now = datetime.now(tz)
        it = croniter(cron_expr, now)
        next_dt = it.get_next(datetime)
        # Always store in UTC so SQLite string comparison works correctly
        return next_dt.astimezone(timezone.utc).isoformat()
    except Exception:
        return None


async def parse_reminder(input_text: str, timezone_name: str) -> dict:
    try:
        tz = pytz.timezone(timezone_name)
    except Exception:
        tz = pytz.UTC

    current_dt = datetime.now(tz).isoformat()

    system_prompt = (
        "You are a reminder parser. Given a natural language reminder description "
        "and the user's current date/time and timezone, extract the structured reminder fields.\n"
        f"Current date and time: {current_dt}. User timezone: {timezone_name}.\n\n"
        "Date defaulting rules (apply in order):\n"
        "1. If the user specifies a full date+time, use it exactly.\n"
        "2. If the user says 'tonight' or 'this evening', always use TODAY's date — "
        "   never move it to tomorrow regardless of the current time.\n"
        "3. If only a time is given (no date, no weekday, and no 'tonight'/'this evening'), assume TODAY. "
        "   If that time has already passed today, assume TOMORROW instead.\n"
        "4. If a weekday is given without a date, use the next upcoming occurrence of that weekday.\n"
        "5. Only return fireAt=null if no time whatsoever can be inferred.\n\n"
        "Return valid cron expressions for recurring reminders (use numeric weekdays, e.g. 1=Monday)."
    )

    response = await get_client().chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": input_text},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": REMINDER_SCHEMA,
        },
    )

    result = json.loads(response.choices[0].message.content)

    # Compute nextFireAt if cron
    next_fire = None
    if result.get("cronExpression"):
        next_fire = compute_next_fire(result["cronExpression"], timezone_name)

    return {
        "reminder": {
            "title": result["title"],
            "body": result.get("body"),
            "type": result["type"],
            "fireAt": result.get("fireAt"),
            "cronExpression": result.get("cronExpression"),
            "timezone": timezone_name,
        },
        "confidence": result["confidence"],
        "rawInterpretation": result["rawInterpretation"],
        "nextFireAt": next_fire,
    }
