"""Notes plugin — durable memory with full-text recall."""
from pathlib import Path

from pa.plugins import Command, NLHandler, PluginBase
from pa.plugins.notes.commands import handle_note, handle_notes_nl, handle_recall

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


class NotesPlugin(PluginBase):
    name = "notes"
    description = "Save notes and recall anything ever said (FTS5, fully local)"
    version = "0.1.0"

    def schema_sql(self) -> str:
        return _SCHEMA_PATH.read_text(encoding="utf-8")

    def commands(self) -> list[Command]:
        return [
            Command(name="note", description="Save a note", handler=handle_note),
            Command(name="recall", description="Search notes + conversation history",
                    handler=handle_recall),
        ]

    def nl_handlers(self) -> list[NLHandler]:
        return [
            NLHandler(
                keywords=["note:", "note that", "remember this", "remember that",
                          "jot down", "what was that", "what did i say about",
                          "when did i mention", "find my note"],
                handler=handle_notes_nl,
                description="Save a note, or recall past notes and conversations",
                priority=11,
                intent_id="notes.recall",
                examples=["note: gate code is 4482",
                          "what was that plumber's name",
                          "when did I mention the furnace filter"],
            ),
        ]

    def system_prompt_fragment(self) -> str:
        return (
            "Durable notes: 'note: ...' saves a fact; /recall or questions like "
            "'what was that X' search notes and conversation history locally."
        )
