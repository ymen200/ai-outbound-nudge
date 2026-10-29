"""
Test script to send a marketing email about home grown chicken.
Target: benmansour.mohamed@esprit.tn
"""
import sys
sys.path.insert(0, '.')

from app.send_tools import send_email

# Test email to sell home grown chicken
target_email = "benmansour.mohamed@esprit.tn"
subject = "🐔 Des Poulets Fermiers Élevés avec Amour - Directement chez vous!"

body = """
Bonjour Mohamed,

J'espère que ce message vous trouve bien!

Je me permets de vous contacter car je sais que vous appréciez la qualité et l'authenticité. 

Je représente Ferme Familiale Sidi Bouzid, une ferme familiale qui élève des poulets fermiers dans les meilleures conditions:

🌿 ÉLEVÉS EN PLEIN AIR - Nos poulets profitent d'espace vert et de soleil
🌾 ALIMENTATION NATURELLE - Céréales locales, sans OGM ni antibiotiques
⏱️ ÉLEVÉS PLUS LONGTEMPS - 90-120 jours minimum (vs 35 jours industriels)
🚚 LIVRAISON FRAÎCHE - Directement de notre ferme à votre porte

💰 PRIX SPÉCIAL:
- Poulet entier fermier: 25 DT/kg
- Livraison gratuite à Tunis et banlieue
- Commande minimum: 2 poulets

Nos clients disent:
"Le goût de mon enfance! La viande est ferme et savoureuse." - Client satisfait

🎁 OFFRE LANCEMENT:
Pour toute première commande, recevez -10% avec le code POULET10

Pour commander ou plus d'infos, répondez simplement à cet email ou appelez:
📞 29 123 456

Merci de soutenir l'agriculture locale tunisienne!

Cordialement,
Ahmed Ben Ali
Ferme Familiale Sidi Bouzid
Sidi Bouzid, Tunisie

P.S. - Les stocks sont limités car nous élevons en petites quantités pour garantir la qualité. Réservez dès maintenant!
"""

print("=" * 60)
print("SENDING TEST EMAIL - HOME GROWN CHICKEN")
print("=" * 60)
print(f"\nTo: {target_email}")
print(f"Subject: {subject}")
print(f"\nBody preview: {body[:150]}...")
print("-" * 60)

result = send_email(
    to_address=target_email,
    subject=subject,
    body=body
)

if result["success"]:
    print(f"\n✅ Email sent successfully to {result['to']}")
else:
    print(f"\n❌ Failed to send email: {result['error']}")
    print("\nMake sure you have GMAIL_ADDRESS and GMAIL_APP_PASSWORD set in .env")

print("=" * 60)
