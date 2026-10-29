"""
Cron — Mise à jour périodique des entreprises.

1. Sélection : companies dont la version CURRENT a >= CRON_COMPANY_MAX_AGE_DAYS jours
2. Company  : Apollo + SmartScraperAI -> import_merged_profiles / bulk_import_companies
3. Intent    : request_enrich_company_intents
4. Personas  : request_enrich_company_personas (+ signals LinkedIn)

Usage :
    python cron_company_update.py --dry-run
    python cron_company_update.py --max-age-days 7 --limit 5
    python cron_company_update.py --output cron_queue.json
"""

import argparse
import json
import sys
from datetime import datetime

import config
from database_manager import Neo4jManager


def _serialize_datetime(value):
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def select_companies_for_update(max_age_days: int, limit: int):
    """Retourne les entreprises éligibles à une mise à jour."""
    db = Neo4jManager()
    try:
        return db.get_companies_due_for_update(max_age_days=max_age_days, limit=limit)
    finally:
        db.close()


def run_company_update(company: dict) -> dict:
    """
    Met à jour une entreprise : profil, intent, personas et signals.
    """
    from main_discovery import (
        request_enrich_company_intents,
        request_enrich_company_personas,
        request_refresh_company,
    )

    apollo_id = company.get("apollo_id")
    domain = company.get("domain")
    country = company.get("country")
    global_industry = company.get("global_industry")

    if not apollo_id:
        raise ValueError("apollo_id manquant pour la mise à jour.")

    label = company.get("name") or domain or apollo_id
    print(f"\n--- Mise a jour : {label} ---")

    company_result = request_refresh_company(
        apollo_id=apollo_id,
        domain=domain,
        global_industry=global_industry,
        target_country=country,
    )
    if company_result.get("status") == "error":
        raise RuntimeError(company_result.get("message", "Echec refresh company"))

    apollo_id = company_result.get("apollo_id") or apollo_id
    country = country or company_result.get("country")

    intents_result = request_enrich_company_intents([apollo_id], target_country=country)
    personas_result = request_enrich_company_personas(
        [apollo_id],
        target_country=country,
        limit=config.CRON_PERSONA_LIMIT_PER_COMPANY,
        limit_per_element=config.CRON_PERSONA_LIMIT_PER_ELEMENT,
    )

    return {
        "apollo_id": apollo_id,
        "domain": company_result.get("domain") or domain,
        "company": company_result,
        "intents": intents_result,
        "personas": personas_result,
    }


def run_cron_batch(
    max_age_days: int = None,
    limit: int = None,
    dry_run: bool = False,
    output: str = None,
) -> int:
    """
    Execute une passe cron complete. Retourne un code sortie (0 = OK).
    Utilisee par le CLI et par APScheduler.
    """
    max_age_days = config.CRON_COMPANY_MAX_AGE_DAYS if max_age_days is None else max_age_days
    limit = config.CRON_COMPANY_BATCH_LIMIT if limit is None else limit

    print(
        f"\n[Cron] Recherche des entreprises a mettre a jour "
        f"(age >= {max_age_days} jours, limite={limit})..."
    )

    companies = select_companies_for_update(
        max_age_days=max_age_days,
        limit=limit,
    )

    if not companies:
        print("Aucune entreprise eligible pour le moment.")
        return 0

    print(f"{len(companies)} entreprise(s) selectionnee(s) :\n")
    for idx, company in enumerate(companies, start=1):
        age_days = company.get("age_days", "?")
        last_refresh = _serialize_datetime(company.get("last_refresh"))
        print(
            f"  {idx}. {company.get('name') or 'N/A'} "
            f"| domain={company.get('domain')} "
            f"| apollo_id={company.get('apollo_id')} "
            f"| age={age_days}j "
            f"| last_refresh={last_refresh}"
        )

    if dry_run:
        if output:
            payload = {
                "generated_at": datetime.now().isoformat(),
                "mode": "dry-run",
                "max_age_days": max_age_days,
                "limit": limit,
                "count": len(companies),
                "companies": [
                    {
                        **company,
                        "captured_at": _serialize_datetime(company.get("captured_at")),
                        "last_verified_at": _serialize_datetime(company.get("last_verified_at")),
                        "last_refresh": _serialize_datetime(company.get("last_refresh")),
                    }
                    for company in companies
                ],
            }
            with open(output, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            print(f"\nListe sauvegardee dans : {output}")
        print("\nMode dry-run : aucune mise a jour lancee.")
        return 0

    print("\nLancement des mises a jour...")
    results = {"success": [], "failed": []}

    for company in companies:
        apollo_id = company.get("apollo_id") or company.get("domain")
        try:
            update_result = run_company_update(company)
            results["success"].append(update_result)
            print(f"OK {apollo_id}")
        except Exception as exc:
            print(f"ERREUR {apollo_id} : {exc}")
            results["failed"].append({"id": apollo_id, "error": str(exc)})

    report = {
        "generated_at": datetime.now().isoformat(),
        "max_age_days": max_age_days,
        "limit": limit,
        "success_count": len(results["success"]),
        "failed_count": len(results["failed"]),
        "success": results["success"],
        "failed": results["failed"],
    }

    if output:
        with open(output, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False, default=str)
        print(f"\nRapport sauvegarde dans : {output}")

    print(
        f"\nTermine — succes: {len(results['success'])}, "
        f"echecs: {len(results['failed'])}"
    )
    return 0 if not results["failed"] else 1


def main():
    parser = argparse.ArgumentParser(
        description="Met a jour les entreprises eligibles (company, intent, personas, signals)."
    )
    parser.add_argument(
        "--max-age-days",
        type=int,
        default=config.CRON_COMPANY_MAX_AGE_DAYS,
        help="Age minimum (jours) depuis la derniere version pour declencher une mise a jour.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=config.CRON_COMPANY_BATCH_LIMIT,
        help="Nombre maximum d'entreprises a traiter par execution.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Liste les entreprises eligibles sans lancer la mise a jour.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Chemin JSON optionnel pour sauvegarder la selection ou le rapport final.",
    )
    args = parser.parse_args()

    return run_cron_batch(
        max_age_days=args.max_age_days,
        limit=args.limit,
        dry_run=args.dry_run,
        output=args.output,
    )


if __name__ == "__main__":
    sys.exit(main())
