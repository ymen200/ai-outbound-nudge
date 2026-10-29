import json
import requests
import re
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional
import config
from llm_helpers import PERSONA_POST_ANALYSIS, invoke_template
from llm_provider import get_llm_client, get_llm_model
from unipile_api_trace import (
    UnipileApiTracker,
    compute_session_consumption,
    save_token_report,
    save_trace_json,
)


class PersonaPostScraper:
    def __init__(self):
        self.unipile_api_key = config.UNIPILE_API_KEY
        self.unipile_dsn = (config.UNIPILE_DSN or "").strip().rstrip("/")
        self.unipile_account_id = None  # resolved lazily via ensure_unipile_account_id()
        self.unipile_headers = {
            "X-API-KEY": self.unipile_api_key,
            "accept": "application/json",
            "content-type": "application/json",
        }

        self.llm_client = get_llm_client()
        self.llm_model = get_llm_model()

    def _resolve_account_id(self) -> str:
        if self.unipile_account_id:
            return self.unipile_account_id
        from unipile_account import ensure_unipile_account_id

        self.unipile_account_id = ensure_unipile_account_id()
        return self.unipile_account_id

    def _parse_datetime_safe(self, value):
        if not value:
            return None
        try:
            normalized = value.replace("Z", "+00:00")
            dt = datetime.fromisoformat(normalized)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            return None

    def _trace_identifier_from_url(self, linkedin_url: str) -> str:
        profile_path = linkedin_url.split("linkedin.com/in/")[-1].strip(" /")
        return profile_path.replace("/", "_") or "unknown"

    def _fetch_unipile_posts(
        self,
        linkedin_url,
        days_back,
        max_posts,
        tracker: Optional[UnipileApiTracker] = None,
        trace_operation: Optional[str] = None,
        trace_identifier: Optional[str] = None,
    ):
        """Récupère les posts via l'API Unipile (Flux d'activité direct)"""
        account_id = self._resolve_account_id()
        url_raw = f"{self.unipile_dsn}/api/v1/linkedin"
        payload_raw = {"account_id": account_id, "request_url": linkedin_url}

        try:
            resp_raw = requests.post(url_raw, headers=self.unipile_headers, json=payload_raw)
            if tracker:
                tracker.record(
                    endpoint="/api/v1/linkedin",
                    method="POST",
                    status_code=resp_raw.status_code,
                    headers=dict(resp_raw.headers),
                    success=resp_raw.status_code == 200,
                )
            if resp_raw.status_code != 200:
                print(f"   [Unipile] ⚠️ Échec Raw Data (Statut {resp_raw.status_code})")
                return []
            raw_data = resp_raw.json()
            if trace_operation and trace_identifier:
                save_trace_json(
                    "responses",
                    trace_operation,
                    trace_identifier,
                    "raw_profile",
                    {
                        "request_url": linkedin_url,
                        "status_code": resp_raw.status_code,
                        "data": raw_data,
                    },
                )
        except Exception as e:
            if tracker:
                tracker.record(
                    endpoint="/api/v1/linkedin",
                    method="POST",
                    status_code=0,
                    success=False,
                )
            print(f"   [Unipile] ⚠️ Erreur requête Raw Data : {e}")
            return []

        text_dump = json.dumps(raw_data)
        ids = re.findall(r"ACo[A-Za-z0-9_-]+", text_dump)
        if not ids:
            print("   [Unipile] ⚠️ Impossible de trouver le Member ID.")
            return []
        member_id = ids[0]

        url_posts = f"{self.unipile_dsn}/api/v1/linkedin/search?account_id={account_id}"
        payload_posts = {
            "api": "classic",
            "category": "posts",
            "posted_by": {"member": [member_id]},
            "sort_by": "date",
        }

        try:
            resp_posts = requests.post(url_posts, headers=self.unipile_headers, json=payload_posts)
            if tracker:
                tracker.record(
                    endpoint="/api/v1/linkedin/search",
                    method="POST",
                    status_code=resp_posts.status_code,
                    headers=dict(resp_posts.headers),
                    success=resp_posts.status_code == 200,
                )
            if resp_posts.status_code != 200:
                print(f"   [Unipile] ⚠️ Échec Search Posts (Statut {resp_posts.status_code})")
                return []
            posts_data = resp_posts.json()
            if trace_operation and trace_identifier:
                save_trace_json(
                    "responses",
                    trace_operation,
                    trace_identifier,
                    "search_posts",
                    {
                        "member_id": member_id,
                        "status_code": resp_posts.status_code,
                        "data": posts_data,
                    },
                )
        except Exception as e:
            if tracker:
                tracker.record(
                    endpoint="/api/v1/linkedin/search",
                    method="POST",
                    status_code=0,
                    success=False,
                )
            print(f"   [Unipile] ⚠️ Erreur requête Search Posts : {e}")
            return []

        posts = []
        cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)

        for p in posts_data.get("items", []):
            dt = self._parse_datetime_safe(p.get("parsed_datetime"))
            if dt is None or dt < cutoff:
                continue

            posts.append({
                "id": p.get("id"),
                "date": p.get("parsed_datetime"),
                "content": p.get("text"),
                "linkedinUrl": p.get("share_url"),
            })

        posts.sort(key=lambda x: x.get("date", ""), reverse=True)
        return posts[:max_posts]

    def fetch_persona_signals(
        self,
        linkedin_url,
        posted_limit: Optional[str] = None,
        target_count: Optional[int] = None,
        output_filename="persona_signals.json",
        trace_operation: Optional[str] = None,
        trace_identifier: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Extraction Unipile puis enrichissement LLM (résultats générés en anglais).
        posted_limit et target_count sont lus depuis .env si non fournis.
        """
        resolved_posted_limit = posted_limit or config.UNIPILE_POSTED_LIMIT
        resolved_target_count = target_count or config.UNIPILE_TARGET_COUNT
        days_back = config.get_unipile_days_back(resolved_posted_limit)

        print(f"🔍 Recherche de signaux pour : {linkedin_url}")
        print(
            f"   Config Unipile : posted_limit={resolved_posted_limit} ({days_back}j), "
            f"target_count={resolved_target_count}"
        )

        resolved_trace_operation = trace_operation or "persona_posts"
        resolved_trace_identifier = trace_identifier or self._trace_identifier_from_url(linkedin_url)
        unipile_tracker = UnipileApiTracker()
        initial_unipile_report = None

        print("📊 [0] Capture de l'état initial Unipile...")
        account_id = self._resolve_account_id()
        initial_unipile_report, _ = save_token_report(
            operation=resolved_trace_operation,
            identifier=resolved_trace_identifier,
            suffix="initial",
            api_key=self.unipile_api_key,
            dsn=self.unipile_dsn,
            account_id=account_id,
        )

        print("🔄 [1] Lancement de l'extraction via UNIPILE (Flux direct)...")
        final_items = self._fetch_unipile_posts(
            linkedin_url,
            days_back,
            resolved_target_count,
            tracker=unipile_tracker,
            trace_operation=resolved_trace_operation,
            trace_identifier=resolved_trace_identifier,
        )

        if final_items:
            print(f"✅ [1] Unipile a réussi ! {len(final_items)} posts trouvés.")
        else:
            print("ℹ️ [1] Unipile n'a retourné aucun résultat.")

        session_consumption = compute_session_consumption(
            unipile_tracker,
            extra={
                "posts_retrieved": len(final_items),
                "linkedin_url": linkedin_url,
                "posted_limit": resolved_posted_limit,
                "target_count": resolved_target_count,
            },
        )
        save_token_report(
            operation=resolved_trace_operation,
            identifier=resolved_trace_identifier,
            suffix="final",
            api_key=self.unipile_api_key,
            dsn=self.unipile_dsn,
            account_id=account_id,
            session_diff=session_consumption,
        )
        print(
            f"   • Appels API Unipile consommés : {session_consumption['api_calls_consumed']} "
            f"(succès: {session_consumption['successful_calls']}, échecs: {session_consumption['failed_calls']})"
        )

        if not final_items:
            print("❌ Aucun post trouvé.")
            return {
                "posts": [],
                "unipile_session_consumption": session_consumption,
                "unipile_initial_report": initial_unipile_report,
            }

        print(
            f"🤖 [2] Analyse sémantique LLM ({self.llm_client.provider}) "
            "(Output: English)..."
        )
        for index, post in enumerate(final_items, 1):
            content = post.get("content", "").strip()

            if not content:
                post["businessSignal"] = "No textual content available to analyze."
                post["personaInterest"] = "N/A"
                post["keyTakeaway"] = "N/A"
                continue

            print(f"   -> Analyse du post {index}/{len(final_items)} (ID: {post.get('id')})...")
            try:
                raw_content = invoke_template(
                    PERSONA_POST_ANALYSIS,
                    content=content,
                    temperature=0.2,
                    max_tokens=400,
                    fallback="",
                    operation="persona_post_analysis",
                ).strip()

                if raw_content.startswith("```json"):
                    raw_content = raw_content[7:]
                elif raw_content.startswith("```"):
                    raw_content = raw_content[3:]
                if raw_content.endswith("```"):
                    raw_content = raw_content[:-3]

                raw_content = raw_content.strip()

                analysis_result = json.loads(raw_content)
                post["businessSignal"] = analysis_result.get("businessSignal", "Not found")
                post["personaInterest"] = analysis_result.get("personaInterest", "Not found")
                post["keyTakeaway"] = analysis_result.get("keyTakeaway", "Not found")

            except Exception as e:
                print(f"   ⚠️ Erreur lors de l'analyse du post {post.get('id')} : {e}")
                post["businessSignal"] = "Error during extraction."
                post["personaInterest"] = "Analysis unavailable."
                post["keyTakeaway"] = "Unable to generate summary."

        with open(output_filename, "w", encoding="utf-8") as json_file:
            json.dump(final_items, json_file, ensure_ascii=False, indent=4)

        print(f"💾 Résultats épurés et enrichis enregistrés avec succès dans : {output_filename}")
        return {
            "posts": final_items,
            "unipile_session_consumption": session_consumption,
            "unipile_initial_report": initial_unipile_report,
        }


if __name__ == "__main__":
    scraper = PersonaPostScraper()

    target_profile_url = "https://www.linkedin.com/in/amany-fathallah-hr/"
    scrape_result = scraper.fetch_persona_signals(
        linkedin_url=target_profile_url,
        output_filename="linkedin_persona_signals.json",
    )
    posts_data = scrape_result.get("posts", []) if isinstance(scrape_result, dict) else scrape_result
