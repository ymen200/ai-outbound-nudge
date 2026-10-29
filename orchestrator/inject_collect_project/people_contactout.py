import requests
import json

# Clé API ContactOut
CONTACTOUT_API_KEY = "1SaBV3N21IkAxAZFzqsmusAE"

def search_personas_by_domain(
    domain: str, 
    job_titles: list = None, 
    reveal_info: bool = False, 
    page_size: int = 1
):
    """
    Recherche les profils d'employés (personas) associés à un nom de domaine spécifique,
    en éliminant les données de l'entreprise (company) pour chaque profil.
    
    :param domain: Le nom de domaine de l'entreprise (ex: "esprit.tn" ou "google.com")
    :param job_titles: Liste optionnelle de postes à cibler (ex: ["CEO", "Manager"])
    :param reveal_info: Si True, dévoile les emails et numéros de téléphone (consomme des crédits)
    :param page_size: Nombre de profils à récupérer par page (max 25)
    """
    print(f"--- Recherche de Personas par Domaine ---")
    print(f"🌐 Domaine ciblé : {domain}")
    if job_titles:
        print(f"💼 Rôles ciblés  : {job_titles}")
    print(f"📞 Récupération directe des coordonnées (reveal_info) : {reveal_info}\n")

    url = "https://api.contactout.com/v1/people/search"
    
    headers = {
        "accept": "application/json",
        "Content-Type": "application/json",
        "token": CONTACTOUT_API_KEY
    }
    
    # Construction du payload selon la documentation officielle
    payload = {
        "domain": [domain],            # Le domaine doit obligatoirement être un tableau (array)
        "page": 1,
        "page_size": min(page_size, 25),
        "current_company_only": True,  # S'assurer qu'ils y travaillent actuellement
        "reveal_info": reveal_info,    # True pour récupérer directement e-mails et numéros de téléphone
        "detailed_experience": True,   # Retourne l'historique de carrière structuré
        "detailed_education": True ,   # Retourne le parcours académique structuré
        "detailed_experience": True
    }
    
    # Si des postes spécifiques sont ciblés, on les ajoute au payload
    if job_titles:
        payload["job_title"] = job_titles

    try:
        response = requests.post(url, headers=headers, json=payload)
        
        if response.status_code == 200:
            results = response.json()
            print("✅ Recherche de personnes réussie !")
            
            metadata = results.get("metadata", {})
            total_results = metadata.get("total_results", 0)
            print(f"📊 Nombre total de profils trouvés : {total_results}")
            
            profiles = results.get("profiles", {})
            
            if not profiles:
                print("ℹ️ Aucun profil correspondant trouvé pour ce domaine.")
            else:
                print(f"👥 {len(profiles)} profil(s) récupéré(s) sur cette page.")
                
                # Parcours des profils pour supprimer la clé 'company' de chacun d'eux
                for profile_url, profile_data in list(profiles.items()):
                    # Suppression de la clé 'company' si elle existe
                    profile_data.pop("company", None)
                    
                    name = profile_data.get("full_name", "Inconnu")
                    title = profile_data.get("title", "Non spécifié")
                    print(f"   - {name} ({title}) -> {profile_url}")
            
            # Enregistrement des résultats (sans la partie 'company') dans un fichier JSON dédié
            output_filename = f"personas_{domain.replace('.', '_')}.json"
            with open(output_filename, "w", encoding="utf-8") as f:
                json.dump(results, f, indent=4, ensure_ascii=False)
                
            print(f"\n💾 Les profils ont été sauvegardés dans : {output_filename}")
            return results

        elif response.status_code == 400:
            print("❌ Erreur 400 : Requête invalide.")
            print("Détail de l'erreur :", response.text)
            return None
        elif response.status_code == 401:
            print("❌ Erreur 401 : Authentification échouée. Vérifiez votre clé API.")
            return None
        else:
            print(f"❌ Erreur {response.status_code} : {response.text}")
            return None
            
    except Exception as e:
        print(f"❌ Une erreur est survenue lors de la recherche : {e}")
        return None


if __name__ == "__main__":
    # EXEMPLE D'UTILISATION :
    # Nous cherchons les employés associés à un domaine (ex: contactout.com)
    # sans filtrer par poste pour l'instant et en révélant les emails.
    search_personas_by_domain(
        domain="allianz.fr",
        job_titles=["Sales"], # Optionnel : à commenter/retirer pour tout récupérer
        reveal_info=True,                                     # Attention : consomme des crédits de révélation
        page_size=3
    )