import os
import json
import sys
import argparse
import requests
import time
import config

def poll_webhook_result(request_id: str, max_attempts: int = 5, delay: int = 6):
    api_key = config.APOLLO_API_KEY

    # Endpoint officiel corrigé au singulier (sans 's')
    url = f"https://api.apollo.io/api/v1/webhook_result/{request_id}"
    
    headers = {
        "Cache-Control": "no-cache",
        "Content-Type": "application/json",
        "accept": "application/json",
        "X-Api-Key": api_key
    }

    print(f"\n🔍 Interrogation de l'endpoint Webhook Apollo pour l'ID : {request_id}")
    print(f"⏳ Maximum de tentatives : {max_attempts} (Intervalle : {delay}s)\n")

    for attempt in range(1, max_attempts + 1):
        print(f"🔄 Tentative {attempt}/{max_attempts}...")
        try:
            response = requests.get(url, headers=headers)
            
            if response.status_code == 401:
                print("❌ Erreur 401 : Clé API non valide.")
                return
            elif response.status_code == 404:
                print("⚠️ Statut 404 : ID de requête introuvable ou pas encore traité par Apollo.")
            elif response.status_code == 200:
                data = response.json()
                status = data.get("webhook_status")
                
                print(f"       ↳ Statut actuel d'Apollo : [{status}]")
                
                if status == "success":
                    print("🎉 Succès ! Données récupérées d'Apollo.")
                    
                    # Extraction et mise en valeur des numéros de téléphone trouvés
                    webhook_res_payload = data.get("webhook_result", {})
                    if webhook_res_payload:
                        people_list = webhook_res_payload.get("people", [])
                        for person in people_list:
                            phones = person.get("phone_numbers", [])
                            if phones:
                                print(f"\n📞 NUMÉROS DE TÉLÉPHONE TROUVÉS POUR {person.get('id', 'Contact')} :")
                                print(json.dumps(phones, indent=2))
                            else:
                                print("\nℹ️ Le statut est un succès mais la liste 'phone_numbers' est vide pour ce profil.")
                    
                    # Sauvegarde automatique du payload complet pour ton traitement
                    output_file = f"webhook_result_{request_id}.json"
                    with open(output_file, "w", encoding="utf-8") as f:
                        json.dump(data, f, indent=2, ensure_ascii=False)
                    print(f"\n💾 Payload complet extrait et sauvegardé dans : {output_file}")
                    return data
                
                elif status == "failed":
                    print(f"❌ Le traitement asynchrone a échoué chez Apollo. Raison : {data.get('failure_reason')}")
                    return data
                
                elif status == "in_progress":
                    print("⏳ Toujours en cours de traitement côté serveur...")
            else:
                print(f"⚠️ Réponse inattendue du serveur (Code {response.status_code})")
                
        except Exception as e:
            print(f"❌ Une erreur est survenue lors de la requête : {e}")
            
        time.sleep(delay)
        
    print("\n⚠️ Fin des tentatives. Le numéro prend plus de temps à être généré ou l'asynchronisme a expiré.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Script de Polling ciblé pour récupérer les résultats de Webhook d'Apollo.")
    parser.add_argument("--request_id", type=str, required=True, help="Le request_id fourni par le script d'enrichissement.")
    args = parser.parse_args()

    poll_webhook_result(request_id=args.request_id)