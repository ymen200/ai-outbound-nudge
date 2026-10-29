import requests
import json

# Clé API ContactOut
CONTACTOUT_API_KEY = "1SaBV3N21IkAxAZFzqsmusAE"

def enrich_domains(domains: list):
    """
    Prend une liste de domaines et récupère leurs données d'enrichissement.
    """
    if not domains:
        print("⚠️ Aucun domaine à enrichir.")
        return None

    print(f"\n⚡ Lancement de l'enrichissement pour {len(domains)} domaine(s) : {domains}")
    url = "https://api.contactout.com/v1/domain/enrich"
    
    headers = {
        "accept": "application/json",
        "Content-Type": "application/json",
        "token": CONTACTOUT_API_KEY
    }
    
    payload = {
        "domains": domains
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        
        if response.status_code == 200:
            enrich_data = response.json()
            print("✅ Enrichissement réussi !")
            return enrich_data
        else:
            print(f"❌ Échec de l'enrichissement ({response.status_code}) : {response.text}")
            return None
            
    except Exception as e:
        print(f"❌ Une erreur est survenue lors de l'enrichissement : {e}")
        return None


def search_and_enrich_companies(country: str, industry: str, size: str):
    print(f"--- Recherche d'entreprises (POST) ---")
    print(f"📍 Localisation : {country} | 🏢 Secteur : {industry} | 👥 Taille : {size}\n")
    
    url = "https://api.contactout.com/v1/company/search"
    
    headers = {
        "accept": "application/json",
        "Content-Type": "application/json",
        "token": CONTACTOUT_API_KEY
    }
    
    # Payload mis à jour avec le paramètre 'location' et filtres stricts
    payload = {
        "location": [country],
        "industries": [industry],
        "size": [size],
        "hq_only": True,
        "limit": 10
    }
    
    try:
        # 1. Recherche des entreprises
        response = requests.post(url, headers=headers, json=payload)
        
        if response.status_code == 200:
            search_results = response.json()
            print("✅ Recherche réussie !")
            
            companies = search_results.get("companies", [])
            
            if not companies:
                print("\nℹ️ Note : La liste 'companies' est vide pour ces critères. Impossible d'enrichir.")
                # Sauvegarde du résultat vide tout de même
                with open("contactout_results.json", "w", encoding="utf-8") as f:
                    json.dump(search_results, f, indent=4, ensure_ascii=False)
                return

            # 2. Extraction des domaines uniques trouvés
            # (On filtre les valeurs nulles ou vides au cas où)
            domains = list(set([c.get("domain") for c in companies if c.get("domain")]))
            print(f"🔗 {len(domains)} domaine(s) extrait(s) des résultats : {domains}")
            
            # 3. Enrichissement des domaines trouvés
            enrich_results = enrich_domains(domains)
            
            # 4. Structuration du résultat final pour notre fichier JSON
            final_output = {
                "search_criteria": {
                    "location": country,
                    "industry": industry,
                    "size": size
                },
                "search_results": search_results,
                "enrichment_results": enrich_results
            }
            
            # 5. Enregistrement dans le fichier de sortie
            output_filename = "contactout_results.json"
            with open(output_filename, "w", encoding="utf-8") as f:
                json.dump(final_output, f, indent=4, ensure_ascii=False)
                
            print(f"\n💾 Les résultats combinés ont été enregistrés dans : {output_filename}")
            
        elif response.status_code == 400:
            print(f"❌ Erreur 400 : Requête invalide.")
            print("Détail de l'erreur :", response.text)
        elif response.status_code == 401:
            print("❌ Erreur 401 : Authentification échouée.")
        else:
            print(f"❌ Erreur {response.status_code} : {response.text}")
            
    except Exception as e:
        print(f"❌ Une erreur est survenue lors de la requête : {e}")


if __name__ == "__main__":
    search_and_enrich_companies(
        country="Tunisia", 
        industry="Law Practice", 
        size="11_50"
    )