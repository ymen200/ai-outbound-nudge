import requests
import json
import re
import os
from dotenv import load_dotenv

load_dotenv()

# --- CONFIGURATION ---
SERPER_API_KEY = os.getenv("SERPER_API_KEY")
HUNTER_API_KEY = os.getenv("HUNTER_API_KEY")
if not SERPER_API_KEY or not HUNTER_API_KEY:
    raise ValueError("SERPER_API_KEY et HUNTER_API_KEY doivent être définies dans .env")
COMPANY_DOMAIN = "vermeg.com"
QUERY = 'site:linkedin.com/in/ "Vermeg" "Tunisia"'
OUTPUT_FILE = "vermeg_hunter_test.json"

def clean_linkedin_name(raw_name):
    """Nettoie les scories de LinkedIn pour avoir un nom propre pour Hunter"""
    # 1. Enlever les caractères invisibles (Right-to-Left mark utilisé en arabe)
    clean = raw_name.replace('\u200f', '').replace('\u200e', '')
    
    # 2. Couper au premier séparateur (|, ,, -, ou emojis fréquents)
    clean = re.split(r'[|,\-]', clean)[0]
    
    # 3. Nettoyer les espaces superflus
    return clean.strip()

def split_name(full_name):
    """Sépare le prénom et le nom pour l'API Hunter"""
    parts = full_name.split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    
    # On assume que le premier mot est le prénom, le reste est le nom de famille
    first_name = parts[0]
    last_name = " ".join(parts[1:])
    return first_name, last_name

def get_hunter_data(first_name, last_name):
    """Interroge Hunter.io pour trouver l'email et le poste exact"""
    if not first_name or not last_name:
        return "Non trouvé", "Non trouvé"
        
    print(f"   🔍 Recherche Hunter pour: {first_name} {last_name}...")
    
    url = f"https://api.hunter.io/v2/email-finder?domain={COMPANY_DOMAIN}&first_name={first_name}&last_name={last_name}&api_key={HUNTER_API_KEY}"
    
    try:
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json().get("data", {})
            email = data.get("email") or "Non trouvé"
            position = data.get("position") or "Non trouvé"
            return email, position
        elif response.status_code == 404:
            return "Non trouvé par Hunter", "Non trouvé"
        elif response.status_code == 401:
            return "Erreur clé API Hunter", "Erreur"
        else:
            return f"Erreur {response.status_code}", ""
    except Exception as e:
        return f"Erreur système: {e}", ""

def search_and_enrich():
    url = "https://google.serper.dev/search"
    
    payload = json.dumps({
        "q": QUERY,
        "gl": "tn",
        "hl": "fr",
        "num": 3  # On en cherche 10 sur Google au cas où il y a des faux profils
    })
    
    headers = {
        'X-API-KEY': SERPER_API_KEY,
        'Content-Type': 'application/json'
    }

    print(f"📡 Étape 1 : Recherche Serper (Google)...")

    try:
        response = requests.post(url, headers=headers, data=payload)
        
        if response.status_code == 200:
            results = response.json()
            organic_results = results.get("organic", [])
            final_profiles = []
            
            print(f"📡 Étape 2 : Traitement et enrichissement Hunter (Limité à 3 profils max)")
            
            # ⚠️ LIMITATION À 3 PROFILS POUR SAUVER LES CRÉDITS ⚠️
            for item in organic_results[:3]:
                title_raw = item.get("title", "")
                link = item.get("link", "")
                
                # Extraction basique du nom depuis le titre Google
                raw_full_name = title_raw.split(" - ")[0]
                
                # Nettoyage profond
                clean_full_name = clean_linkedin_name(raw_full_name)
                first_name, last_name = split_name(clean_full_name)
                
                # Appel à l'API Hunter
                hunter_email, hunter_position = get_hunter_data(first_name, last_name)
                
                final_profiles.append({
                    "raw_name_from_google": raw_full_name,
                    "clean_name_used": clean_full_name,
                    "linkedin_url": link,
                    "company": "Vermeg",
                    "hunter_email": hunter_email,
                    "hunter_title": hunter_position,
                    "source": "Serper + Hunter.io"
                })

            with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
                json.dump(final_profiles, f, indent=4, ensure_ascii=False)

            print(f"✅ Terminé ! {len(final_profiles)} profils testés et sauvegardés.")
            print(f"💾 Regarde le résultat dans : {OUTPUT_FILE}")
            
        else:
            print(f"❌ Erreur Serper HTTP {response.status_code}")

    except Exception as e:
        print(f"❌ Erreur globale : {e}")

if __name__ == "__main__":
    search_and_enrich()