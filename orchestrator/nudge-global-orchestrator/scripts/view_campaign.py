"""Inspect a campaign stored in the orchestrator database."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.store import store


def main() -> None:
    cid = sys.argv[1] if len(sys.argv) > 1 else None
    db = store

    if not cid:
        with db._conn() as conn:
            rows = conn.execute(
                "SELECT id, status, stage, updated_at FROM campaigns ORDER BY updated_at DESC LIMIT 10"
            ).fetchall()
        print("Recent campaigns:")
        for r in rows:
            row = dict(r) if hasattr(r, "keys") else {"id": r[0], "status": r[1], "stage": r[2], "updated_at": r[3]}
            print(
                f"  {row['id']}  status={row['status']}  stage={row['stage']}  updated={row['updated_at']}"
            )
        print("\nUsage: python scripts/view_campaign.py <campaign_id>")
        return

    camp = db.get_campaign(cid)
    if not camp:
        print(f"Campaign not found: {cid}")
        raise SystemExit(1)

    print("=" * 70)
    print("CAMPAIGN")
    print("=" * 70)
    for k, v in camp.items():
        if k in ("raw_icp", "user_offering") and isinstance(v, str) and len(v) > 160:
            v = v[:160] + "..."
        if k == "icp_features_json" and v:
            try:
                v = json.dumps(json.loads(v), indent=2)
            except Exception:
                pass
        print(f"{k}: {v}")

    print("\n" + "=" * 70)
    print("ARTIFACTS (stage summaries)")
    print("=" * 70)
    artifacts = db.list_artifacts(cid)

    for art in artifacts:
        stage = art["stage"]
        payload = art["payload"]
        print(f"\n--- {stage} @ {art['created_at']} ---")
        if not isinstance(payload, dict):
            print(type(payload), str(payload)[:300])
            continue

        if stage == "fetch_companies":
            companies = payload.get("companies") or []
            print(f"count={payload.get('count')} companies={len(companies)} error={payload.get('error')}")
            for c in companies[:3]:
                print(
                    " ",
                    {
                        "apollo_id": c.get("apollo_id"),
                        "name": c.get("name"),
                        "domain": c.get("domain"),
                    },
                )
        elif stage in ("rank_companies", "rescore_intent"):
            ranked = payload.get("ranked_companies") or []
            print(
                f"status={payload.get('status')} ranked={len(ranked)} "
                f"nurture={len(payload.get('nurture_companies') or [])} error={payload.get('error')}"
            )
            for c in ranked[:5]:
                metrics = c.get("qualification_metrics") or {}
                print(
                    " ",
                    c.get("apollo_id"),
                    c.get("name"),
                    f"total={metrics.get('total_score')} firm={metrics.get('firmographic_score')} "
                    f"intent={metrics.get('intent_score')} tier={metrics.get('tier')}",
                )
        elif stage == "fetch_intent":
            intent = payload.get("intent_by_apollo_id") or {}
            print(f"companies_with_intent={len(intent)} error={payload.get('error')}")
            for apollo_id, body in list(intent.items())[:5]:
                print(
                    " ",
                    apollo_id,
                    "jobs=",
                    len((body or {}).get("job_offers") or []),
                    "news=",
                    len((body or {}).get("news") or []),
                    "status=",
                    (body or {}).get("status"),
                )
        elif stage == "fetch_personas":
            pb = payload.get("sourced_personas_by_company") or {}
            print(f"error={payload.get('error')}")
            for apollo_id, personas in pb.items():
                print(f"  {apollo_id}: {len(personas or [])} personas")
                for p in (personas or [])[:3]:
                    print("   ", p.get("apollo_id") or p.get("name"), p.get("title"))
        elif stage == "rank_personas":
            ranked = payload.get("ranked_personas") or []
            print(
                f"status={payload.get('status')} ranked_personas={len(ranked)} "
                f"total={payload.get('total_personas_ranked')} error={payload.get('error')}"
            )
            for p in ranked[:10]:
                print(" ", p)
        elif stage == "enrich_contacts":
            contacts = payload.get("contacts") or {}
            print(f"contacts={len(contacts)} error={payload.get('error')} warning={payload.get('warning')}")
        elif stage == "final_packages":
            packages = payload.get("packages") or []
            print(f"packages={len(packages)}")
            if packages:
                print(json.dumps(packages[0], indent=2, default=str)[:2000])
        elif stage == "error":
            print(payload)
        else:
            keys = list(payload.keys())
            print(f"keys={keys}")
            if "icp_filters" in payload:
                print("icp_filters=", json.dumps(payload.get("icp_filters"), indent=2)[:800])
            if "error" in payload and payload.get("error"):
                print("error=", payload.get("error"))

    packages = db.list_packages(cid)
    print("\n" + "=" * 70)
    print(f"FINAL PACKAGES TABLE: {len(packages)}")
    print("=" * 70)
    for p in packages:
        print(f"\nlead_id={p['lead_id']} created={p['created_at']}")
        print(json.dumps(p["package"], indent=2, default=str)[:2500])

    out = ROOT / "data" / f"campaign_{cid}.json"
    dump = {
        "campaign": camp,
        "artifacts": artifacts,
        "packages": [p["package"] for p in packages],
    }
    out.write_text(json.dumps(dump, indent=2, default=str), encoding="utf-8")
    print(f"\nFull dump written to: {out}")


if __name__ == "__main__":
    main()
