"""A customer opening a category's screen, counted beside the documents made with it.

The admin's category report (operations/metrics.category_report) sets how
often each category was chosen beside how often one was made. The bot counts
a tap on a category's button, the web the opening of its screen: the same
moment, one step before the description. Only the category's id is kept,
never anything the customer wrote.
"""
# A customer who opens a category, looks at its examples and comes back, or
# rewords their description, has chosen it once: openings this close together
# are one choice, in the bot and on the web alike, so the admin's
# chosen-versus-made compares like with like.
WINDOW_SECONDS = 30 * 60


def record(account, category, channel):
    """Count that `account` opened `category` in `channel` ('bot' or 'web'). Never raises."""
    try:
        from django.core.cache import cache
        from apps.core.funnel import environment
        from apps.core.models import AnalyticsEvent
        from . import catalogue
        entry = catalogue.get(category)
        if entry is None or not cache.add(f'category-chosen:{account.pk}:{entry.id}', 1, WINDOW_SECONDS):
            return
        AnalyticsEvent.objects.create(
            account=account, event_type=catalogue.CHOSEN_EVENT, feature_id=entry.feature_id, channel=channel,
            locale=getattr(account, 'locale', '') or 'en', plan_at_event=getattr(account, 'plan', '') or 'free',
            environment=environment(account), properties={'category': entry.id})
    except Exception:
        # Counting is never worth a customer's request failing.
        return
