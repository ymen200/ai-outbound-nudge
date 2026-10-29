import requests
import json
import time
import os
from dotenv import load_dotenv

load_dotenv()

# --- CONFIGURATION ---
HUNTER_API_KEY = os.getenv("HUNTER_API_KEY")
if not HUNTER_API_KEY:
    raise ValueError("HUNTER_API_KEY manquante dans .env")
COMPANY_DOMAIN = "vermeg.com"
OUTPUT_FILE = "vermeg_sales_with_phone.json"

def get_extra_details(email):
    """
    Appelle l'enrichissement pour récupérer le numéro de téléphone et autres extras.
    """
    url = "https://api.hunter.io/v2/people/find"
    params = {"email": email, "api_key": HUNTER_API_KEY}
    try:
        response = requests.get(url, params=params)
        if response.status_code == 200:
            data = response.json().get("data", {})
            return {
                "phone_number": data.get("phone_number"),
                "linkedin": data.get("linkedin"),
                "city": data.get("city"),
                "country": data.get("country")
            }
        return {}
    except Exception:
        return {}

def fetch_vermeg_personas():
    # 1. Recherche initiale des membres
    url = "https://api.hunter.io/v2/domain-search"
    params = {
        "domain": COMPANY_DOMAIN,
        "api_key": HUNTER_API_KEY,
        "limit": 10 
    }

    print(f"📡 Recherche des profils pour : {COMPANY_DOMAIN}...")
    
    try:
        response = requests.get(url, params=params)
        if response.status_code == 200:
            data = response.json()
            emails = data.get("data", {}).get("emails", [])
            
            final_personas = []
            
            # On cherche les profils cibles
            targets = []
            for person in emails:
                pos = (person.get("position") or "").lower()
                dept = (person.get("department") or "").lower()
                if any(k in pos for k in ["sales", "business", "commercial", "strategy", "director"]) or dept == "sales":
                    targets.append(person)
                if len(targets) >= 2: break

            if len(targets) < 2: targets = emails[:2]

            # 2. Phase d'extraction du téléphone et enrichissement
            for p in targets:
                email = p.get("value")
                print(f"📞 Tentative d'extraction du téléphone pour : {email}")
                
                # Infos de base
                persona = {
                    "first_name": p.get("first_name"),
                    "last_name": p.get("last_name"),
                    "full_name": f"{p.get('first_name')} {p.get('last_name')}",
                    "title": p.get("position", "Employee"),
                    "email": email,
                    "phone_number": None, # Par défaut
                    "linkedin": p.get("linkedin"),
                    "source": "Hunter.io"
                }

                # Récupération du téléphone via enrichment
                extra = get_extra_details(email)
                if extra.get("phone_number"):
                    persona["phone_number"] = extra["phone_number"]
                
                # Si le search n'avait pas le linkedin mais l'enrichment oui
                if not persona["linkedin"] and extra.get("linkedin"):
                    handle = extra["linkedin"]
                    persona["linkedin"] = f"https://www.linkedin.com/in/{handle}" if "linkedin.com" not in str(handle) else handle

                final_personas.append(persona)
                time.sleep(1) # Respect du quota

            # Sauvegarde
            with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
                json.dump(final_personas, f, indent=4, ensure_ascii=False)
            
            print(f"✅ Terminé ! Fichier généré : {OUTPUT_FILE}")
            
        else:
            print(f"❌ Erreur API : {response.status_code}")

    except Exception as e:
        print(f"❌ Erreur : {e}")

if __name__ == "__main__":
    fetch_vermeg_personas()