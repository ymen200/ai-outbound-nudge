"""
Full AI Pipeline test with guardrails.
Uses Message Generator for AI generation + quality check + human review flow.
Target: Mohamed Benmansour at Esprit
Quality threshold: 80 (default)
"""
import httpx
import asyncio

MSG_GEN_API = "http://localhost:8000"

TARGET = {
    "name": "Mohamed Benmansour",
    "email": "benmansour.mohamed@esprit.tn",
    "company": "Esprit",
    "title": "Responsable Informatique"
}

async def generate_message():
    """Step 1: AI Generate message with quality check."""
    print("=" * 70)
    print("🤖 AI PIPELINE TEST - WITH GUARDRAILS")
    print("=" * 70)
    print(f"\n🎯 Target: {TARGET['name']} ({TARGET['email']})")
    print(f"🏢 {TARGET['company']} - {TARGET['title']}")
    print(f"🚜 Sender: Ferme Familiale Sidi Bouzid")
    print(f"⚙️  Quality Threshold: 80/100")
    print("-" * 70)
    
    payload = {
        "target_prospect": TARGET['name'],
        "target_company": TARGET['company'],
        "prospect_role": TARGET['title'],
        "channel": "email",
        "intent": "direct_outreach",
        "stage": "first_touch",
        "personality": {
            "base_template": "soft_sell",
            "personality_traits": ["professional", "respectful", "concise"],
            "never_use_phrases": ["cheap", "bargain", "act now", "limited time"],
            "touchdowns_per_message": 2,
            "urgency_level": 1
        },
        "company_details": {
            "company_name": "Ferme Familiale Sidi Bouzid",
            "elevator_pitch": "Nous élevons des poulets fermiers de qualité supérieure. Note: vous avez parlé la semaine dernière avec un étudiant à propos des poulets fermiers et de l'alimentation locale - c'est exactement ce que nous proposons.",
            "value_props": [
                "Élevage en plein air et alimentation naturelle",
                "Viande ferme et savoureuse",
                "Livraison fraîche à domicile"
            ],
            "social_proof": ["Plus de 1000 familles satisfaites"]
        },
        "selected_offer": {
            "offer_name": "Découverte Poulet Fermier",
            "pain_points": [
                "Difficulté à trouver de la viande de qualité traçable",
                "Manque de temps pour se rendre aux marchés fermiers"
            ],
            "solution_summary": "Livraison directe de poulets fermiers frais, élevés naturellement, à prix juste. Contexte: vous avez discuté la semaine dernière avec un étudiant à propos des poulets fermiers et de l'alimentation locale.",
            "proof_points": ["95% de clients satisfaits", "Note 4.8/5"],
            "cta": "Répondez à cet email pour commander avec -10% de réduction (code POULET10)."
        },
        "research_context": {
            "recent_activity": "A discuté avec un étudiant la semaine dernière au sujet des poulets fermiers et de l'importance d'une alimentation saine et locale",
            "interests": ["alimentation saine", "produits locaux", "qualité de vie"],
            "hook": "Vous avez parlé la semaine dernière avec l'un de vos étudiants à propos des poulets fermiers et de l'alimentation locale"
        }
    }
    
    print("\n[1] AI Message Generation + Quality Check")
    print(f"    POST {MSG_GEN_API}/api/generate/simple")
    print(f"    MIN_QUALITY_SCORE: 80 (from env)")
    
    async with httpx.AsyncClient(timeout=300.0) as client:
        response = await client.post(f"{MSG_GEN_API}/api/generate/simple", json=payload)
        result = response.json()
    
    print("\n" + "=" * 70)
    print("📊 GENERATION RESULT")
    print("=" * 70)
    
    if result.get('success') and not result.get('awaiting_human'):
        # Auto-approved (score >= 80)
        print(f"✅ AUTO-APPROVED (Score: {result.get('score')}/100 ≥ 80)")
        print(f"Subject: {result.get('subject')}")
        print(f"Message: {result.get('message', '')[:200]}...")
        return result
    
    elif result.get('awaiting_human'):
        # Needs human review (score < 80)
        print(f"⏳ HUMAN REVIEW REQUIRED")
        print(f"   Score: {result.get('score', 'N/A')}/100 < 80")
        print(f"   Task ID: {result.get('task_id')}")
        print(f"   Review URL: {result.get('review_url')}")
        print("-" * 70)
        print(f"Message preview:")
        print(f"{result.get('message', '')[:250]}...")
        return result
    
    else:
        print(f"❌ Generation failed: {result.get('error')}")
        return None

async def approve_and_send(task_id, message_data):
    """Step 2: Approve via human review endpoint and send."""
    print("\n" + "=" * 70)
    print("👤 HUMAN REVIEW - APPROVING")
    print("=" * 70)
    
    approval = {
        "approved": True,
        "prospect_email": TARGET['email']
    }
    
    print(f"\n[2] Approving and sending...")
    print(f"    POST {MSG_GEN_API}/api/review/{task_id}/decision")
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{MSG_GEN_API}/api/review/{task_id}/decision",
            json=approval
        )
        result = response.json()
    
    if result.get('success'):
        print(f"\n✅ APPROVED & SENT!")
        print(f"   Channel: {result.get('result', {}).get('channel')}")
        print(f"   To: {result.get('result', {}).get('to')}")
        return True
    else:
        print(f"\n❌ Failed: {result}")
        return False

async def main():
    # Step 1: Generate
    result = await generate_message()
    if not result:
        return
    
    # Step 2: Handle based on status
    if result.get('awaiting_human'):
        task_id = result.get('task_id')
        await approve_and_send(task_id, result)
    elif result.get('success'):
        print(f"\n📧 Message was auto-approved and is ready to send")
        # Could call send endpoint here if needed
    
    print("\n" + "=" * 70)
    print("[✓] Full AI Pipeline Complete!")
    print("   Flow: Generate → Quality Check → (Review) → Send")
    print("=" * 70)

if __name__ == "__main__":
    asyncio.run(main())
