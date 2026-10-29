import os
import json
import sys
import time
import requests
from typing import Dict, Any, Optional
import config
from apollo_api_trace import build_trace_path, save_trace_json

class ApolloPersonaEnricher:
    def __init__(self):
        self.api_key = config.APOLLO_API_KEY
        
        self.match_url = "https://api.apollo.io/api/v1/people/match"
        self.usage_stats_url = "https://api.apollo.io/api/v1/usage_stats/api_usage_stats"
        self.user_profile_url = "https://api.apollo.io/api/v1/users/api_profile"
        
        self.headers = {
            "Content-Type": "application/json",
            "Cache-Control": "no-cache",
            "accept": "application/json",
            "X-Api-Key": self.api_key
        }
        
    def generate_and_save_token_report(self, output_filename: str = "apollo_tokens_report.json", session_diff: Dict[str, Any] = None) -> Dict[str, Any]:
        report_data = {"monthly_credits": {}, "active_rate_limits": {}}
        if session_diff:
            report_data["session_consumption"] = session_diff
        
        print("\n" + "📊 RAPPORT DE CONSOMMATION DES CRÉDITS APOLLO ".center(60, "="))
        
        try:
            params = {"include_credit_usage": "true"}
            user_res = requests.get(self.user_profile_url, headers=self.headers, params=params)
            if user_res.status_code == 200:
                user_data = user_res.json()
                report_data["monthly_credits"] = {
                    "id": user_data.get("id"),
                    "first_name": user_data.get("first_name"),
                    "last_name": user_data.get("last_name"),
                    "email": user_data.get("email"),
                    "num_credits_remaining": user_data.get("num_credits_remaining"),
                    "effective_num_lead_credits": user_data.get("effective_num_lead_credits"),
                    "num_lead_credits_used": user_data.get("num_lead_credits_used"),
                    "effective_num_direct_dial_credits": user_data.get("effective_num_direct_dial_credits"),
                    "num_direct_dial_credits_used": user_data.get("num_direct_dial_credits_used"),
                    "total_unified_credits_used": user_data.get("total_unified_credits_used")
                }
                credits = report_data["monthly_credits"]
                print(f"\n💳 État Actuel des Crédits Mensuels :")
                print(f"   👤 {credits['first_name']} {credits['last_name']} ({credits['email']})")
                print(f"   ↳ [Leads]        Restant : {credits['num_credits_remaining']} | Utilisé : {credits['num_lead_credits_used']}/{credits['effective_num_lead_credits']}")
                print(f"   ↳ [Direct Dial]  Utilisé : {credits['num_direct_dial_credits_used']}/{credits['effective_num_direct_dial_credits']}")
        except Exception as e:
            print(f"⚠️ Erreur crédits : {e}")

        try:
            usage_res = requests.post(self.usage_stats_url, headers=self.headers, json={})
            if usage_res.status_code == 200:
                usage_data = usage_res.json()
                target_keywords = ["match", "people", "enrich"]
                for key, val in usage_data.items():
                    if any(kw in str(key).lower() for kw in target_keywords) and isinstance(val, dict):
                        report_data["active_rate_limits"][str(key)] = val
        except Exception as e:
            print(f"⚠️ Erreur limites : {e}")
            
        print("\n" + "="*60)
        try:
            with open(output_filename, "w", encoding="utf-8") as f:
                json.dump(report_data, f, indent=2, ensure_ascii=False)
        except IOError:
            pass
        return report_data

    def poll_and_extract_waterfall_data(
        self,
        request_id: str,
        max_attempts: int = 8,
        delay: int = 8,
        trace_operation: Optional[str] = None,
        trace_identifier: Optional[str] = None,
    ) -> Dict[str, list]:
        """ Interroge l'endpoint asynchrone et extrait les numéros et emails enrichis """
        url = f"https://api.apollo.io/api/v1/webhook_result/{request_id}"
        print(f"\n🔍 Mode Auto-Polling activé pour l'ID Waterfall : {request_id}")
        
        for attempt in range(1, max_attempts + 1):
            print(f"🔄 Récupération des données Waterfall (Tentative {attempt}/{max_attempts})...")
            try:
                response = requests.get(url, headers=self.headers)
                if response.status_code == 200:
                    data = response.json()
                    status = data.get("webhook_status")
                    
                    if status == "success":
                        print("🎉 Données asynchrones récupérées avec succès !")
                        if trace_operation and trace_identifier:
                            save_trace_json(
                                "responses",
                                trace_operation,
                                trace_identifier,
                                f"webhook_{request_id}",
                                data,
                            )
                        webhook_res = data.get("webhook_result", {})
                        people_list = webhook_res.get("people", [])
                        if people_list:
                            person_data = people_list[0]
                            return {
                                "phone_numbers": person_data.get("phone_numbers", []),
                                "emails": person_data.get("emails", [])
                            }
                        return {"phone_numbers": [], "emails": []}
                    elif status == "failed":
                        print(f"❌ Le traitement a échoué chez Apollo : {data.get('failure_reason')}")
                        return {"phone_numbers": [], "emails": []}
                    elif status == "in_progress":
                        print("⏳ Waterfall toujours en cours côté Apollo...")
                elif response.status_code == 404:
                    print("⏳ Données non prêtes (404)...")
            except Exception as e:
                print(f"⚠️ Erreur lors du polling : {e}")
            
            time.sleep(delay)
        print("⚠️ Fin des tentatives. Les données n'ont pas pu être collectées à temps.")
        return {"phone_numbers": [], "emails": []}

    def enrich_person_by_id(
        self, 
        person_id: str, 
        run_waterfall_email: bool = False,
        run_waterfall_phone: bool = False,
        reveal_personal_emails: bool = False, 
        reveal_phone_number: bool = False,
        webhook_url: str = None,
        trace_operation: Optional[str] = None,
        trace_identifier: Optional[str] = None,
    ) -> Dict[str, Any]:
        query_params = {
            "run_waterfall_email": str(run_waterfall_email).lower(),
            "run_waterfall_phone": str(run_waterfall_phone).lower(),
            "reveal_personal_emails": str(reveal_personal_emails).lower(),
            "reveal_phone_number": str(reveal_phone_number).lower()
        }
        
        payload = {"id": person_id}
        
        is_async = reveal_phone_number or run_waterfall_phone or run_waterfall_email
        if is_async:
            payload["webhook_url"] = webhook_url if webhook_url else "https://httpbin.org/status/200"

        try:
            print(f"🔓 Enrichissement via /people/match pour l'ID : {person_id}...")
            response = requests.post(self.match_url, json=payload, headers=self.headers, params=query_params)
            response.raise_for_status()
            data = response.json()
            
            # Nettoyage initial du bloc organization
            if "person" in data and isinstance(data["person"], dict):
                data["person"].pop("organization", None)
                print("🗑️  Bloc 'organization' éliminé avec succès du profil enrichi.")
                
                # S'assurer que les structures initiales de listes existent
                if "phone_numbers" not in data["person"] or not data["person"]["phone_numbers"]:
                    data["person"]["phone_numbers"] = []
                if "emails" not in data["person"] or not data["person"]["emails"]:
                    data["person"]["emails"] = []
                
                # AUTOMATISATION ET COMBINAISON DIRECTE DU WATERFALL
                req_id = data.get("request_id")
                if req_id and is_async:
                    # Lancement du polling unifié (téléphones + emails)
                    waterfall_data = self.poll_and_extract_waterfall_data(
                        request_id=req_id,
                        trace_operation=trace_operation,
                        trace_identifier=trace_identifier or person_id,
                    )
                    
                    # 1. Fusion unique des NUMÉROS DE TÉLÉPHONE (basée sur l'ID de l'objet)
                    existing_phone_ids = {p.get("id") for p in data["person"]["phone_numbers"] if p.get("id")}
                    added_phones_count = 0
                    for wf_phone in waterfall_data.get("phone_numbers", []):
                        if wf_phone.get("id") not in existing_phone_ids:
                            data["person"]["phone_numbers"].append(wf_phone)
                            existing_phone_ids.add(wf_phone.get("id"))
                            added_phones_count += 1
                    print(f"⚡ {added_phones_count} nouveau(x) numéro(s) ajouté(s) depuis le waterfall.")
                    
                    # 2. Fusion unique des objets complexes d'EMAILS (basée sur la chaîne textuelle)
                    existing_wf_emails = {e.get("email").lower() for e in data["person"]["emails"] if e.get("email")}
                    added_emails_count = 0
                    for wf_email in waterfall_data.get("emails", []):
                        email_str = wf_email.get("email")
                        if email_str and email_str.lower() not in existing_wf_emails:
                            data["person"]["emails"].append(wf_email)
                            existing_wf_emails.add(email_str.lower())
                            added_emails_count += 1
                    print(f"📧 {added_emails_count} nouveau(x) bloc(s) d'email ajouté(s) depuis le waterfall.")

                # 3. Recalcul et normalisation des tableaux d'accès rapides à plat (Téléphones)
                sanitized_list = []
                raw_list = []
                for phone in data["person"]["phone_numbers"]:
                    if isinstance(phone, dict):
                        s_num = phone.get("sanitized_number")
                        r_num = phone.get("raw_number")
                        if s_num and s_num not in sanitized_list:
                            sanitized_list.append(s_num)
                        if r_num and r_num not in raw_list:
                            raw_list.append(r_num)
                
                data["person"]["sanitized_numbers"] = sanitized_list
                data["person"]["raw_numbers"] = raw_list

                # 4. Extraction et dédoublonnage de TOUS les emails au format texte (sanitized_emails)
                sanitized_emails_list = []
                
                # Étape A : Capturer l'email racine s'il existe (généralement issu du reveal standard)
                root_email = data["person"].get("email")
                if root_email:
                    sanitized_emails_list.append(root_email.strip().lower())
                
                # Étape B : Parcourir le tableau d'objets emails complexes fusionné
                for e_obj in data["person"]["emails"]:
                    if isinstance(e_obj, dict):
                        e_str = e_obj.get("email")
                        if e_str:
                            clean_e = e_str.strip().lower()
                            if clean_e not in sanitized_emails_list:
                                sanitized_emails_list.append(clean_e)
                
                # Injection de la liste nettoyée des emails à plat dans "person"
                data["person"]["sanitized_emails"] = sanitized_emails_list
                
                # Si le champ racine "email" était absent/null, on le peuple avec la première valeur trouvée
                if not data["person"].get("email") and sanitized_emails_list:
                    data["person"]["email"] = sanitized_emails_list[0]
                
                print(f"🏷️  Champs d'accès rapide créés : 'sanitized_numbers', 'raw_numbers' et 'sanitized_emails' {sanitized_emails_list}")
                    
            return data
        except requests.exceptions.RequestException as e:
            print(f"❌ Erreur Apollo Match : {e}")
            return {}

    def compute_session_consumption(self, initial_report: Dict[str, Any]) -> Dict[str, Any]:
        session_consumption = {
            "lead_credits_consumed": 0,
            "direct_dial_credits_consumed": 0,
            "ai_credits_consumed": 0,
        }
        try:
            temp_res = requests.get(
                self.user_profile_url,
                headers=self.headers,
                params={"include_credit_usage": "true"},
            )
            if temp_res.status_code == 200:
                temp_data = temp_res.json()
                init_credits = initial_report.get("monthly_credits", {})
                if init_credits and "num_credits_remaining" in init_credits:
                    session_consumption["lead_credits_consumed"] = (
                        init_credits["num_credits_remaining"] - temp_data.get("num_credits_remaining", 0)
                    )
                    session_consumption["direct_dial_credits_consumed"] = (
                        temp_data.get("num_direct_dial_credits_used", 0)
                        - init_credits.get("num_direct_dial_credits_used", 0)
                    )
                    session_consumption["ai_credits_consumed"] = (
                        temp_data.get("num_ai_credits_used", 0)
                        - init_credits.get("num_ai_credits_used", 0)
                    )
        except Exception:
            pass
        return session_consumption


def enrich_person_with_traces(
    person_id: str,
    operation: str,
    run_waterfall_email: bool = False,
    run_waterfall_phone: bool = False,
    reveal_personal_emails: bool = False,
    reveal_phone_number: bool = False,
    webhook_url: str = None,
) -> Dict[str, Any]:
    """
    Enrichit un persona via Apollo /people/match et archive tokens + réponse JSON.
    """
    enricher = ApolloPersonaEnricher()
    initial_report = enricher.generate_and_save_token_report(
        output_filename=build_trace_path("tokens", operation, person_id, "initial")
    )
    match_result = enricher.enrich_person_by_id(
        person_id=person_id,
        run_waterfall_email=run_waterfall_email,
        run_waterfall_phone=run_waterfall_phone,
        reveal_personal_emails=reveal_personal_emails,
        reveal_phone_number=reveal_phone_number,
        webhook_url=webhook_url,
        trace_operation=operation,
        trace_identifier=person_id,
    )
    save_trace_json("responses", operation, person_id, "people_match", match_result or {})
    session_consumption = enricher.compute_session_consumption(initial_report)
    enricher.generate_and_save_token_report(
        output_filename=build_trace_path("tokens", operation, person_id, "final"),
        session_diff=session_consumption,
    )
    return match_result or {}

if __name__ == "__main__":
    enricher = ApolloPersonaEnricher()
    
    target_person_id = "6516758fc6e667000141b22f"  
    waterfall_email = True
    waterfall_phone = True
    reveal_emails = True
    reveal_phone = True
    test_webhook = None 
    
    # 1. Rapport de crédits initial
    initial_report = enricher.generate_and_save_token_report()
    
    # 2. Exécution unifiée : Demande -> Polling global -> Fusion Totale Dédoublonnée
    combined_result = enricher.enrich_person_by_id(
        person_id=target_person_id,
        run_waterfall_email=waterfall_email,
        run_waterfall_phone=waterfall_phone,
        reveal_personal_emails=reveal_emails,
        reveal_phone_number=reveal_phone,
        webhook_url=test_webhook
    )
    
    # 3. Sauvegarde du fichier unique combiné final
    if combined_result:
        output_filename = "enriched_persona_match.json"
        try:
            with open(output_filename, "w", encoding="utf-8") as f:
                json.dump(combined_result, f, indent=2, ensure_ascii=False)
            print(f"\n💾 Fichier combiné final (Téléphones + Emails unifiés) sauvegardé : {output_filename}")
        except IOError as e:
            print(f"❌ Erreur écriture : {e}")
            
    # 4. Calcul et affichage final des crédits
    session_consumption = {"lead_credits_consumed": 0, "direct_dial_credits_consumed": 0, "ai_credits_consumed": 0}
    try:
        temp_res = requests.get(enricher.user_profile_url, headers=enricher.headers, params={"include_credit_usage": "true"})
        if temp_res.status_code == 200:
            temp_data = temp_res.json()
            init_credits = initial_report.get("monthly_credits", {})
            if init_credits and "num_credits_remaining" in init_credits:
                session_consumption["lead_credits_consumed"] = init_credits["num_credits_remaining"] - temp_data.get("num_credits_remaining", 0)
                session_consumption["direct_dial_credits_consumed"] = temp_data.get("num_direct_dial_credits_used", 0) - init_credits["num_direct_dial_credits_used"]
    except Exception:
        pass

    enricher.generate_and_save_token_report(session_diff=session_consumption)