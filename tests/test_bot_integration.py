import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from pa.bot.bot import PABot
from pa.config.config import Config
from pa.vault.vault import Vault
from pa.store.store import Store
from pa.brain.brain import Brain
from pa.scrapers.mfa_bridge import MFABridge


def _make_update(user_id: int, text: str, is_command: bool = False):
    update = MagicMock()
    update.effective_user.id = user_id
    update.message.text = text
    update.message.delete = AsyncMock()
    update.message.reply_text = AsyncMock()
    update.message.chat_id = user_id
    update.effective_chat.send_message = AsyncMock()
    return update


def _make_context(**user_data):
    ctx = MagicMock()
    ctx.user_data = dict(user_data)
    return ctx


@pytest.fixture
async def bot_deps(tmp_dir, sample_config):
    config = Config(sample_config)
    await config.load()
    vault = Vault(tmp_dir)
    await vault.init("test-password")
    store = Store(tmp_dir / "test.db")
    await store.connect()
    await store.init_schema()
    brain = MagicMock(spec=Brain)
    mfa = MFABridge()
    bot = PABot(config=config, vault=vault, store=store, brain=brain, mfa_bridge=mfa)
    yield bot
    await store.close()


async def test_unauthorized_user_ignored(bot_deps):
    bot = bot_deps
    update = _make_update(user_id=999, text="/balance")
    context = _make_context()
    await bot._handle_balance(update, context)
    update.message.reply_text.assert_not_called()


async def test_handle_balance(bot_deps):
    bot = bot_deps
    acc_id = await bot._store.add_account("wf", "WF Checking", "checking")
    await bot._store.add_balance(acc_id, balance=1500.00)
    update = _make_update(user_id=123456789, text="/balance")
    context = _make_context()
    await bot._handle_balance(update, context)
    reply = update.message.reply_text.call_args[0][0]
    assert "$1,500.00" in reply


async def test_handle_unlock_sets_awaiting_password(bot_deps):
    bot = bot_deps
    update = _make_update(user_id=123456789, text="/unlock")
    context = _make_context()
    await bot._handle_unlock(update, context)
    assert context.user_data["awaiting_password"] is True


async def test_password_message_deleted(bot_deps):
    bot = bot_deps
    bot._vault.lock()
    update = _make_update(user_id=123456789, text="test-password")
    context = _make_context(awaiting_password=True)
    prompt_msg = MagicMock()
    prompt_msg.delete = AsyncMock()
    context.user_data["_prompt_message"] = prompt_msg
    await bot._handle_message(update, context)
    update.message.delete.assert_called_once()
    prompt_msg.delete.assert_called_once()


async def test_handle_message_routes_to_brain(bot_deps):
    bot = bot_deps
    bot._brain.query = AsyncMock(return_value="Your total debt is $5,000")
    update = _make_update(user_id=123456789, text="how much do I owe?")
    context = _make_context()
    await bot._handle_message(update, context)
    reply = update.message.reply_text.call_args[0][0]
    assert "$5,000" in reply


async def test_vault_locked_rejects_brain_query(bot_deps):
    bot = bot_deps
    bot._vault.lock()
    update = _make_update(user_id=123456789, text="how much do I owe?")
    context = _make_context()
    await bot._handle_message(update, context)
    reply = update.message.reply_text.call_args[0][0]
    assert "locked" in reply.lower()
