import requests
import json
import re
import os
from dotenv import load_dotenv

load_dotenv()

# --- CONFIGURATION ---
SERPER_API_KEY = os.getenv("SERPER_API_KEY")
if not SERPER_API_KEY:
    raise ValueError("SERPER_API_KEY manquante dans .env")
QUERY = 'site:linkedin.com/in/ "Vermeg" "Tunisia"'
OUTPUT_FILE = "vermeg_enriched_profiles.json"

def extract_phone(text):
    # Cherche des formats de numéros tunisiens (+216, 00216, ou 8 chiffres)
    phone_pattern = r"(\+216|00216)?[\s.-]?\d{2}[\s.-]?\d{3}[\s.-]?\d{3}"
    match = re.search(phone_pattern, text)
    return match.group(0) if match else "Non trouvé"

def extract_email(text):
    # Cherche des patterns d'emails standards
    email_pattern = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
    match = re.search(email_pattern, text)
    return match.group(0) if match else "Non trouvé"

def search_vermeg_profiles():
    url = "https://google.serper.dev/search"
    
    payload = json.dumps({
        "q": QUERY,
        "gl": "tn",
        "hl": "fr",
        "num": 20  # Augmenté pour avoir plus de profils
    })
    
    headers = {
        'X-API-KEY': SERPER_API_KEY,
        'Content-Type': 'application/json'
    }

    print(f"📡 Recherche et enrichissement des profils Vermeg...")

    try:
        response = requests.post(url, headers=headers, data=payload)
        
        if response.status_code == 200:
            results = response.json()
            organic_results = results.get("organic", [])
            final_profiles = []
            
            for item in organic_results:
                title_raw = item.get("title", "")
                snippet = item.get("snippet", "")
                link = item.get("link", "")
                
                # --- EXTRACTION DU NOM ET DU POSTE ---
                # Sur LinkedIn, le titre est souvent "Prénom Nom - Poste - Entreprise"
                parts = title_raw.split(" - ")
                name = parts[0].strip()
                
                # Le poste est souvent la deuxième partie
                job_title = parts[1].strip() if len(parts) > 1 else "Employé chez Vermeg"
                
                # --- EXTRACTION DATA (EMAIL, TEL, TWITTER) ---
                # On fouille dans le snippet pour trouver des infos cachées
                email = extract_email(snippet)
                phone = extract_phone(snippet)
                
                # Twitter : On cherche souvent la mention d'un handle @ ou un lien
                twitter_match = re.search(r"@\w{1,15}", snippet)
                twitter = twitter_match.group(0) if twitter_match else "Non trouvé"

                final_profiles.append({
                    "full_name": name,
                    "title": job_title,
                    "company": "Vermeg",
                    "location": "Tunisia",
                    "email": email,
                    "phone": phone,
                    "twitter": twitter,
                    "linkedin_url": link,
                    "snippet_raw": snippet # On garde le snippet pour preuve
                })

            with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
                json.dump(final_profiles, f, indent=4, ensure_ascii=False)

            print(f"✅ Terminé ! {len(final_profiles)} profils enrichis sauvegardés.")
            print(f"💾 Fichier : {OUTPUT_FILE}")
            
        else:
            print(f"❌ Erreur HTTP {response.status_code}")

    except Exception as e:
        print(f"❌ Erreur : {e}")

if __name__ == "__main__":
    search_vermeg_profiles()