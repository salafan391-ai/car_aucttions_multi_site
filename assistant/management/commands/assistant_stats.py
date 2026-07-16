"""Quick text summary of assistant usage.

    python manage.py assistant_stats                 # totals + per-tenant + recent
    python manage.py assistant_stats --days 7        # last 7 days only
    python manage.py assistant_stats --recent 40     # show 40 most-recent questions
    python manage.py assistant_stats --schema ofleet0
    python manage.py assistant_stats --prune 90      # delete rows older than 90 days

Runs against the public-schema table, so it covers every tenant at once. Pass any
DJANGO_SETTINGS_MODULE that points at the shared DB (settings_vps on the server).
"""
from django.core.management.base import BaseCommand
from django.db.models import Count
from django.utils import timezone

from assistant.models import AssistantQuery


class Command(BaseCommand):
    help = "Summarise dashboard help-assistant usage."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=None, help="Limit to the last N days.")
        parser.add_argument("--schema", type=str, default=None, help="One tenant schema only.")
        parser.add_argument("--recent", type=int, default=20, help="How many recent questions to list.")
        parser.add_argument("--prune", type=int, default=None, metavar="DAYS",
                            help="Delete rows older than DAYS and exit.")

    def handle(self, *args, **opts):
        if opts["prune"] is not None:
            cutoff = timezone.now() - timezone.timedelta(days=opts["prune"])
            n, _ = AssistantQuery.objects.filter(created_at__lt=cutoff).delete()
            self.stdout.write(self.style.SUCCESS(f"Pruned {n} rows older than {opts['prune']} days."))
            return

        qs = AssistantQuery.objects.all()
        if opts["days"]:
            qs = qs.filter(created_at__gte=timezone.now() - timezone.timedelta(days=opts["days"]))
        if opts["schema"]:
            qs = qs.filter(schema_name=opts["schema"])

        total = qs.count()
        window = f"last {opts['days']} days" if opts["days"] else "all time"
        scope = f", schema={opts['schema']}" if opts["schema"] else ""
        self.stdout.write(self.style.MIGRATE_HEADING(f"\nAssistant usage ({window}{scope})"))
        self.stdout.write(f"  Total questions: {total}")
        if not total:
            return

        by_status = dict(qs.values_list("status").annotate(n=Count("id")))
        self.stdout.write(
            f"  answered={by_status.get('ok', 0)}  "
            f"errors={by_status.get('error', 0)}  "
            f"rate_limited={by_status.get('rate_limited', 0)}"
        )

        self.stdout.write("\n  By tenant:")
        for row in qs.values("schema_name").annotate(n=Count("id")).order_by("-n"):
            self.stdout.write(f"    {row['schema_name']:24} {row['n']}")

        n = opts["recent"]
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n  {n} most recent questions:"))
        for q in qs.order_by("-created_at")[:n]:
            when = q.created_at.strftime("%Y-%m-%d %H:%M")
            flag = "" if q.status == "ok" else f" [{q.status}]"
            self.stdout.write(f"    {when}  {q.schema_name}/{q.username}{flag}: {q.question[:90]}")
        self.stdout.write("")
