AI Outbound — static frontend
=============================

Brand site + Campaign Studio for the nudge-global-orchestrator API.

Pages
-----
- index.html      Landing (brand hero)
- campaign.html   Campaign Studio — save / load / start params
- results.html    List companies + personas for a campaign_id
- save_campaign.html  Redirects to campaign.html

Run
---
1. Start the API on port 8100:

   cd orchestrator\nudge-global-orchestrator
   .\venv\Scripts\activate
   python scripts\run_api.py

2. Serve this folder (recommended so relative assets load cleanly):

   cd frontend
   python -m http.server 5500

3. Open http://127.0.0.1:5500/

Flow
----
1. Campaign Studio → Save params → Start campaign (copies campaign_id)
2. Results → polls GET /campaigns/{id} (status/stage/artifacts)
3. When ready → List companies / personas → optionally Decline companies

APIs used
---------
- GET  /health
- POST /campaigns/params
- PATCH /campaigns/params/{user_id}
- GET  /campaigns/params/{user_id}
- POST /campaigns/start
- GET  /campaigns/{id}
- GET  /campaigns/{id}/companies
- GET  /campaigns/{id}/personas
- POST /campaigns/{id}/companies/decline

Override API base URL (optional):
  localStorage.setItem("ai_outbound_api", "http://127.0.0.1:8100")
