"""
APScheduler — execution hebdomadaire du cron company update.

Le job part chaque semaine au jour/heure configures.
Au moment du declenchement, le flag CRON_SCHEDULER_ENABLED (true/false)
decide si la mise a jour tourne reellement ou est ignoree.

Usage :
    python cron_scheduler.py
    python cron_scheduler.py --run-now
    python cron_scheduler.py --enabled true
    python cron_scheduler.py --enabled false

Config (.env) :
    CRON_SCHEDULER_ENABLED=true|false
    CRON_SCHEDULER_DAY=mon   # mon..sun
    CRON_SCHEDULER_HOUR=3
    CRON_SCHEDULER_MINUTE=0
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

import config
from cron_company_update import run_cron_batch

VALID_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def _parse_bool_arg(value: str) -> bool:
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"Attendu true/false, recu {value!r}")


def scheduled_company_update_job(force_enabled: bool | None = None) -> None:
    """
    Callback APScheduler.
    force_enabled :
      - None  -> lit CRON_SCHEDULER_ENABLED dans .env au moment du run
      - True/False -> override explicite (CLI)
    """
    now = datetime.now().isoformat(timespec="seconds")
    enabled = (
        force_enabled
        if force_enabled is not None
        else config.is_cron_scheduler_enabled()
    )

    print(f"\n[Scheduler] Declenchement hebdomadaire ({now})")
    print(f"[Scheduler] CRON_SCHEDULER_ENABLED = {enabled}")

    if not enabled:
        print(
            "[Scheduler] Job ignore : CRON_SCHEDULER_ENABLED=false. "
            "Passe a true pour activer la mise a jour."
        )
        return

    print("[Scheduler] Lancement de cron_company_update.run_cron_batch()...")
    exit_code = run_cron_batch()
    print(f"[Scheduler] Termine avec code={exit_code}")


def build_scheduler(day: str, hour: int, minute: int) -> tuple[BlockingScheduler, CronTrigger]:
    if day not in VALID_DAYS:
        raise ValueError(
            f"CRON_SCHEDULER_DAY invalide : {day!r}. "
            f"Valeurs : {', '.join(VALID_DAYS)}"
        )
    if not (0 <= hour <= 23):
        raise ValueError(f"CRON_SCHEDULER_HOUR invalide : {hour}")
    if not (0 <= minute <= 59):
        raise ValueError(f"CRON_SCHEDULER_MINUTE invalide : {minute}")

    scheduler = BlockingScheduler()
    trigger = CronTrigger(day_of_week=day, hour=hour, minute=minute)
    scheduler.add_job(
        scheduled_company_update_job,
        trigger=trigger,
        id="weekly_company_update",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    return scheduler, trigger


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Planifie le cron company update une fois par semaine (APScheduler)."
    )
    parser.add_argument(
        "--enabled",
        type=_parse_bool_arg,
        default=None,
        help="Override true/false du flag CRON_SCHEDULER_ENABLED pour ce process.",
    )
    parser.add_argument(
        "--run-now",
        action="store_true",
        help="Execute une passe immediate (respecte --enabled / .env) puis quitte.",
    )
    parser.add_argument(
        "--day",
        default=config.CRON_SCHEDULER_DAY,
        choices=VALID_DAYS,
        help="Jour hebdomadaire (mon..sun).",
    )
    parser.add_argument(
        "--hour",
        type=int,
        default=config.CRON_SCHEDULER_HOUR,
        help="Heure locale (0-23).",
    )
    parser.add_argument(
        "--minute",
        type=int,
        default=config.CRON_SCHEDULER_MINUTE,
        help="Minute (0-59).",
    )
    args = parser.parse_args()

    if args.enabled is not None:
        os.environ["CRON_SCHEDULER_ENABLED"] = "true" if args.enabled else "false"

    enabled_now = config.is_cron_scheduler_enabled()
    print(
        f"[Scheduler] Config : day={args.day} {args.hour:02d}:{args.minute:02d} | "
        f"enabled={enabled_now}"
    )

    if args.run_now:
        scheduled_company_update_job(force_enabled=args.enabled)
        return 0

    scheduler, trigger = build_scheduler(args.day, args.hour, args.minute)
    next_run = trigger.get_next_fire_time(None, datetime.now())
    print(f"[Scheduler] Prochaine execution planifiee : {next_run}")
    print("[Scheduler] Process actif. Ctrl+C pour arreter.")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        print("\n[Scheduler] Arret demande.")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
