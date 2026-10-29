import requests
import json
import time
import os
from dotenv import load_dotenv

load_dotenv()

# --- CONFIGURATION CONTACTOUT ---
CONTACTOUT_API_KEY = os.getenv("CONTACTOUT_API_KEY")
if not CONTACTOUT_API_KEY:
    raise ValueError("CONTACTOUT_API_KEY manquante dans .env")
COMPANY_NAME = "NASA"
OUTPUT_FILE = "vermeg_contactout_results.json"

# Liste des cibles
TEST_PROFILES = [
    {
        "first_name": "Ryan ",
        "last_name": "McClelland",
        "url": "https://www.linkedin.com/in/ryan-mcclelland-7b00184/"
    },
    {
        "first_name": "Fathi ",
        "last_name": "Karouia",
        "url": "https://www.linkedin.com/in/fathikarouia/"
    }
]

def get_headers():
    return {
        "token": CONTACTOUT_API_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

def enrich_by_linkedin_v1(linkedin_url):
    """
    Endpoint: v1/linkedin/enrich
    """
    api_url = "https://api.contactout.com/v1/linkedin/enrich"
    params = {
        'profile': linkedin_url
    }
    
    try:
        response = requests.get(api_url, headers=get_headers(), params=params, timeout=20)
        
        if response.status_code == 200:
            return response.json()
        else:
            print(f"⚠️ Erreur API {response.status_code} pour {linkedin_url} : {response.text}")
            return None
    except Exception as e:
        print(f"❌ Erreur de connexion : {e}")
        return None

def run_contactout_test():
    final_results = []
    print(f"🚀 Enrichissement VERMEG en cours (Filtre Anti-Mock activé)...")

    for p in TEST_PROFILES:
        full_name = f"{p['first_name']} {p['last_name']}"
        data = enrich_by_linkedin_v1(p['url'])
        
        if data and "profile" in data and isinstance(data["profile"], dict):
            prof = data["profile"]
            
            # --- DÉTECTION DU FAUX PROFIL (MOCK DATA) ---
            actual_name = prof.get('full_name', '')
            if actual_name == "Example Person" or "Legros" in prof.get('company', {}).get('name', ''):
                print(f"🛡️ {full_name} : Rejeté. L'API a renvoyé le profil fictif de démonstration.")
                final_results.append({
                    "searched_name": full_name,
                    "linkedin": p['url'],
                    "status": "Not Found (Mock Data Returned)",
                    "extracted_email": "Non trouvé",
                    "extracted_phone": "Non trouvé"
                })
                time.sleep(2)
                continue # On passe au profil suivant sans enregistrer les fausses données

            # --- EXTRACTION DES DONNÉES RÉELLES ---
            raw_work = prof.get('work_email', [])
            raw_personal = prof.get('personal_email', [])
            raw_phones = prof.get('phone', [])

            # Sécurité supplémentaire au cas où le faux profil change de nom
            def filter_real_data(data_list):
                if not isinstance(data_list, list):
                    data_list = [data_list] if data_list else []
                return [d for d in data_list if "example" not in str(d).lower() and "12345678" not in str(d)]

            emails_work = filter_real_data(raw_work)
            emails_perso = filter_real_data(raw_personal)
            phones = filter_real_data(raw_phones)

            email_final = emails_work[0] if emails_work else (emails_perso[0] if emails_perso else "Non trouvé")
            phone_final = phones[0] if phones else "Non trouvé"

            headline = prof.get('headline', 'N/A')
            company_data = prof.get('company', {})
            actual_company = company_data.get('name', 'N/A') if isinstance(company_data, dict) else 'N/A'

            if email_final == "Non trouvé" and phone_final == "Non trouvé":
                print(f"ℹ️ {actual_name} : Profil trouvé mais coordonnées privées.")
            else:
                print(f"✅ {actual_name} : {email_final} | {phone_final}")

            final_results.append({
                "searched_name": full_name,
                "linkedin": p['url'],
                "actual_name": actual_name,
                "job_headline": headline,
                "current_company": actual_company,
                "extracted_email": email_final,
                "extracted_phone": phone_final,
                "raw_data_found": {
                    "work_emails": emails_work,
                    "personal_emails": emails_perso,
                    "phones": phones,
                    "status": prof.get('work_email_status', {})
                }
            })
        else:
            print(f"❌ {full_name} : Aucun résultat renvoyé.")

        time.sleep(2)

    # Sauvegarde
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(final_results, f, indent=4, ensure_ascii=False)

    print(f"\n✅ Terminé. Fichier propre sauvegardé dans {OUTPUT_FILE}")

if __name__ == "__main__":
    run_contactout_test()