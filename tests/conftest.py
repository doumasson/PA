import json
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def tmp_dir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def sample_config(tmp_dir: Path) -> Path:
    config_path = tmp_dir / "config.json"
    config_path.write_text(json.dumps({
        "telegram_user_id": 123456789,
        "telegram_bot_token_env": "PA_TELEGRAM_TOKEN",
        "claude_api_key_env": "PA_CLAUDE_API_KEY",
        "monthly_income": 5000.0,
        "financial_goals": ["debt-free in 2 years"],
        "preferences": [],
        "schedule": {
            "bank_balance_hours": 4,
            "cc_balance_daily_time": "06:00",
            "transaction_pull_daily_time": "07:00",
            "due_date_check_time": "08:00",
            "weekly_summary_day": "sunday",
            "weekly_summary_time": "19:00",
        },
        "cost_cap_monthly_usd": 20.0,
        "backup_path": "",
    }))
    return config_path
