import os
from groq import Groq

# Initialisation du client avec ta clé API directement
api_key = "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"
client = Groq(api_key=api_key)

# Choix du modèle gratuit (Llama 3.3 70B ou Llama 3.1 8B selon les quotas du moment)
# ID recommandés pour le tier gratuit :
# - "llama-3.3-70b-versatile" (Haute qualité / 70B)
# - "llama-3.1-8b-instant" (Super rapide / 8B)
MODEL_ID = "llama-3.3-70b-versatile"


def test_connection():
    print(f"--- Lancement du test Groq avec le modèle : {MODEL_ID} ---")

    try:
        # Appel à l'API de complétion
        completion = client.chat.completions.create(
            model=MODEL_ID,
            messages=[
                {
                    "role": "system",
                    "content": "Tu es un assistant technique expert et concis."
                },
                {
                    "role": "user",
                    "content": "Fais-moi un salut ultra rapide en 2 phrases et explique pourquoi Groq est si performant."
                }
            ],
            temperature=0.7,
            max_tokens=150
        )

        # Affichage de la réponse
        print("\n🤖 Réponse de Llama :")
        print(completion.choices[0].message.content)
        print("\n✅ Connexion établie avec succès et réponse reçue !")

    except Exception as e:
        print(f"\n❌ Une erreur est survenue lors de l'appel à l'API : {e}")


if __name__ == "__main__":
    test_connection()