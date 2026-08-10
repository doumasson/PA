"""Review plugin — the Sunday sit-down.

A guided weekly review: the week ahead (calendar), money due (bills, budget
state), open tasks, and one Bart-free paragraph of judgment about what
actually matters. Sundays at 17:00, or on demand with /weekreview.
"""
from pa.plugins import Command, Job, NLHandler, PluginBase
from pa.plugins.review.builder import handle_weekreview, job_sunday_review


class ReviewPlugin(PluginBase):
    name = "review"
    description = "Sunday sit-down: guided weekly review of calendar, money, and tasks"
    version = "0.1.0"

    def schema_sql(self) -> str:
        return ""

    def commands(self) -> list[Command]:
        return [
            Command(name="weekreview", description="Run the weekly review now",
                    handler=handle_weekreview),
        ]

    def jobs(self) -> list[Job]:
        return [
            Job(name="sunday_review", handler=job_sunday_review,
                trigger="cron", kwargs={"day_of_week": "sun", "hour": 17, "minute": 0}),
        ]

    def nl_handlers(self) -> list[NLHandler]:
        return [
            NLHandler(
                keywords=["weekly review", "week review", "review my week",
                          "plan my week", "what's my week", "whats my week"],
                handler=_nl_review,
                description="Run the weekly review (week ahead, bills, budget, tasks)",
                priority=13,
                intent_id="review.week",
                examples=["let's do the weekly review", "plan my week",
                          "what's my week look like"],
            ),
        ]

    def system_prompt_fragment(self) -> str:
        return (
            "Weekly review available: /weekreview or 'plan my week' walks "
            "through the week ahead, bills due, budget state, and open tasks."
        )


async def _nl_review(ctx, text, update) -> str:
    from pa.plugins.review.builder import build_review
    return await build_review(ctx)
