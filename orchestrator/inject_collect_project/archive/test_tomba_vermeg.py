import requests
import json
import time
import os
from dotenv import load_dotenv

load_dotenv()

# --- CONFIGURATION TOMBA.IO ---
TOMBA_API_KEY = os.getenv("TOMBA_API_KEY")
TOMBA_API_SECRET = os.getenv("TOMBA_API_SECRET")
if not TOMBA_API_KEY or not TOMBA_API_SECRET:
    raise ValueError("TOMBA_API_KEY et TOMBA_API_SECRET doivent être définies dans .env")
DOMAIN = "vermeg.com"
OUTPUT_FILE = "vermeg_tunisia_staff_phones.json"

HEADERS = {
    'X-Tomba-Key': TOMBA_API_KEY,
    'X-Tomba-Secret': TOMBA_API_SECRET,
    'Content-Type': 'application/json'
}

def get_real_phone(email):
    """Appelle l'endpoint Phone Finder pour obtenir le numéro réel"""
    phone_url = f"https://api.tomba.io/v1/phone-finder?email={email}"
    try:
        response = requests.get(phone_url, headers=HEADERS)
        if response.status_code == 200:
            data = response.json()
            # On récupère le champ phone_number spécifiquement
            return data.get('data', {}).get('phone_number') or "Non trouvé (Privé)"
        return "Non accessible"
    except:
        return "Erreur API"

def fetch_tomba_staff_tunisia():
    # Étape 1 : Domain Search pour lister les gens
    search_url = f"https://api.tomba.io/v1/domain-search/?domain={DOMAIN}"
    
    print(f"📡 Analyse du staff de {DOMAIN} via Tomba...")

    try:
        response = requests.get(search_url, headers=HEADERS)
        
        if response.status_code == 200:
            data = response.json()
            emails_data = data.get('data', {}).get('emails', [])
            
            if not emails_data:
                print("⚠️ Aucun email trouvé.")
                return

            final_staff = []
            
            # Étape 2 : Filtrage et Enrichissement Phone (limité à 3 pour le test)
            count = 0
            for person in emails_data:
                if count >= 3: break # On s'arrête à 3 pour tes crédits
                
                raw_country = person.get('country')
                country = str(raw_country).upper() if raw_country else "UNKNOWN"
                
                # On se concentre sur la Tunisie
                if country == "TN" or country == "UNKNOWN":
                    email = person.get('email')
                    full_name = f"{person.get('first_name', '')} {person.get('last_name', '')}".strip()
                    
                    print(f"🔍 Extraction du numéro pour : {full_name} ({email})...")
                    
                    # --- APPEL AU PHONE FINDER ---
                    real_phone = get_real_phone(email)
                    
                    final_staff.append({
                        "full_name": full_name,
                        "job_title": person.get('position') or "Employé",
                        "email": email,
                        "phone": real_phone, # Ici on aura le vrai numéro ou le motif d'absence
                        "location": country,
                        "linkedin": person.get('linkedin') or "Non trouvé",
                        "source": "Tomba Phone Finder"
                    })
                    
                    count += 1
                    time.sleep(1) # Pause de sécurité pour l'API

            with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
                json.dump(final_staff, f, indent=4, ensure_ascii=False)

            print(f"\n✅ Succès ! {len(final_staff)} profils extraits avec téléphones.")
            for p in final_staff:
                print(f"👤 {p['full_name']} | 📞 {p['phone']}")
            
        else:
            print(f"❌ Erreur API Tomba : {response.status_code}")

    except Exception as e:
        print(f"❌ Erreur système : {e}")

if __name__ == "__main__":
    fetch_tomba_staff_tunisia()