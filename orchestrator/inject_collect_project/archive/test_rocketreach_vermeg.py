import requests
import json
import time
import os
from dotenv import load_dotenv

load_dotenv()

# --- CONFIGURATION ---
ROCKETREACH_API_KEY = os.getenv("ROCKETREACH_API_KEY")
if not ROCKETREACH_API_KEY:
    raise ValueError("ROCKETREACH_API_KEY manquante dans .env")
COMPANY_DOMAIN = "tesla.com"
TARGET_COUNTRY = "USA"
OUTPUT_FILE = "vermeg_domain_results.json"

def fetch_rocketreach_by_domain():
    headers = {
        "Api-Key": ROCKETREACH_API_KEY,
        "Content-Type": "application/json"
    }

    search_url = "https://api.rocketreach.co/v2/api/search"
    
    # Payload structuré : Domaine exact + Localisation précise
    payload = {
        "query": {
            "company_domain": COMPANY_DOMAIN,
            "location": TARGET_COUNTRY
        },
        "page_size": 2
    }

    print(f"📡 Recherche RocketReach : {COMPANY_DOMAIN} localisé en {TARGET_COUNTRY}...")
    
    try:
        response = requests.post(search_url, json=payload, headers=headers)
        
        # Gestion du cas où l'API Free refuse les filtres structurés (Code 400)
        if response.status_code == 400:
            print("🔄 Filtres structurés refusés. Utilisation du mode keyword avec domaine...")
            payload = {
                "query": {
                    "keyword": f"domain:{COMPANY_DOMAIN} location:{TARGET_COUNTRY}"
                },
                "page_size": 5
            }
            response = requests.post(search_url, json=payload, headers=headers)

        if response.status_code in [200, 201]:
            data = response.json()
            profiles = data.get("profiles", [])
            
            if not profiles:
                print(f"⚠️ Aucun staff trouvé pour {COMPANY_DOMAIN} en {TARGET_COUNTRY}.")
                return

            final_personas = []
            print(f"✨ {len(profiles)} profils détectés. Lancement des Lookups...")

            for p in profiles:
                profile_id = p.get("id")
                name = p.get("name", "Inconnu")
                
                # Double vérification : le domaine est-il bien vermeg.com dans le teaser ?
                teaser_domain = p.get("current_employer_domain", "")
                if teaser_domain and teaser_domain != COMPANY_DOMAIN:
                    print(f"⏩ Saut de {name} (Domaine différent : {teaser_domain})")
                    continue

                print(f"🔍 Extraction des contacts pour : {name}")
                
                lookup_url = f"https://api.rocketreach.co/v2/api/lookupProfile?id={profile_id}"
                lookup_res = requests.get(lookup_url, headers=headers)
                
                if lookup_res.status_code in [200, 201]:
                    details = lookup_res.json()
                    
                    # Extraction Email & Téléphone
                    emails = details.get("emails", [])
                    email = details.get("current_work_email") or (emails[0].get("email") if emails else None)
                    
                    phones = details.get("phones", [])
                    phone = next((ph.get("number") for ph in phones if ph.get("type") == "mobile"), 
                                 phones[0].get("number") if phones else None)

                    final_personas.append({
                        "full_name": details.get("name"),
                        "title": details.get("current_title"),
                        "company_domain": COMPANY_DOMAIN,
                        "email": email,
                        "phone_number": phone,
                        "linkedin": details.get("linkedin_url"),
                        "location": details.get("location"),
                        "source": "RocketReach Domain Filter"
                    })
                
                # Pause pour le quota API
                time.sleep(1.5)

            # Sauvegarde
            with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
                json.dump(final_personas, f, indent=4, ensure_ascii=False)
            
            print(f"\n✅ Terminé ! {len(final_personas)} profils sauvegardés dans '{OUTPUT_FILE}'.")
            
        else:
            print(f"❌ Erreur API ({response.status_code}) : {response.text}")

    except Exception as e:
        print(f"❌ Erreur système : {e}")

if __name__ == "__main__":
    fetch_rocketreach_by_domain()