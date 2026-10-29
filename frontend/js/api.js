/** AI Outbound — API helpers */
const API_BASE = localStorage.getItem("ai_outbound_api") || "http://127.0.0.1:8100";
const HEALTH_POLL_MS = 8000;

async function request(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  let data;
  try {
    data = await res.json();
  } catch {
    data = { detail: await res.text() };
  }
  return { ok: res.ok, status: res.status, statusText: res.statusText, data };
}

function saveCampaignParams(body) {
  return request("/campaigns/params", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

function updateCampaignParams(userId, body) {
  return request(`/campaigns/params/${encodeURIComponent(userId)}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

function getCampaignParams(userId) {
  return request(`/campaigns/params/${encodeURIComponent(userId)}`);
}

function startCampaign(userId) {
  return request("/campaigns/start", {
    method: "POST",
    body: JSON.stringify({ user_id: userId }),
  });
}

function listCampaignCompanies(campaignId) {
  return request(`/campaigns/${encodeURIComponent(campaignId)}/companies`);
}

function listCampaignPersonas(campaignId) {
  return request(`/campaigns/${encodeURIComponent(campaignId)}/personas`);
}

function declineCampaignCompanies(campaignId, companyIds) {
  return request(`/campaigns/${encodeURIComponent(campaignId)}/companies/decline`, {
    method: "POST",
    body: JSON.stringify({ company_ids: companyIds }),
  });
}

function getCampaign(campaignId) {
  return request(`/campaigns/${encodeURIComponent(campaignId)}`);
}

async function checkHealth() {
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 4000);
    const res = await fetch(`${API_BASE}/health`, { signal: controller.signal });
    clearTimeout(timer);
    let data = null;
    try {
      data = await res.json();
    } catch {
      data = null;
    }
    return { ok: res.ok, status: res.status, data };
  } catch (err) {
    return { ok: false, status: 0, data: null, error: err };
  }
}

function formatResponse({ status, statusText, data }) {
  return `${status} ${statusText || ""}\n${JSON.stringify(data, null, 2)}`;
}

function initNavScroll() {
  const nav = document.querySelector(".site-nav");
  if (!nav) return;
  const onScroll = () => nav.classList.toggle("is-scrolled", window.scrollY > 8);
  onScroll();
  window.addEventListener("scroll", onScroll, { passive: true });
}

function initHealthBadge() {
  const nav = document.querySelector(".site-nav");
  if (!nav) return;

  let badge = document.getElementById("apiHealthBadge");
  if (!badge) {
    badge = document.createElement("div");
    badge.id = "apiHealthBadge";
    badge.className = "health-badge is-checking";
    badge.setAttribute("role", "status");
    badge.title = `Checking ${API_BASE}/health`;
    badge.innerHTML = `<span class="health-dot" aria-hidden="true"></span><span class="health-text">Checking API…</span>`;

    const links = nav.querySelector(".nav-links");
    if (links) nav.insertBefore(badge, links);
    else nav.appendChild(badge);
  }

  async function refresh() {
    const res = await checkHealth();
    if (res.ok) {
      const mock = res.data && res.data.mock ? " · mock" : "";
      badge.className = "health-badge is-online";
      badge.title = `${API_BASE}/health — online${mock}`;
      badge.querySelector(".health-text").textContent = `API online${mock}`;
    } else {
      badge.className = "health-badge is-offline";
      badge.title = `${API_BASE}/health — unreachable. Start the orchestrator on port 8100.`;
      badge.querySelector(".health-text").textContent = "API offline";
    }
  }

  refresh();
  setInterval(refresh, HEALTH_POLL_MS);
}

document.addEventListener("DOMContentLoaded", () => {
  initNavScroll();
  initHealthBadge();
});
