/** AI Outbound — Campaign results (status poll + companies + personas + decline) */
(function () {
  const POLL_MS = 3000;
  const PHASE_A_STAGES = [
    "created",
    "icp_extract",
    "icp_persisted",
    "fetch_companies",
    "rank_companies",
    "fetch_intent",
    "rescore_intent",
    "fetch_personas",
    "rank_personas",
    "enrich_contacts",
    "package_ready",
  ];

  const campaignInput = document.getElementById("campaign_id");
  const result = document.getElementById("result");
  const statusPill = document.getElementById("statusPill");
  const apiBaseLabel = document.getElementById("apiBaseLabel");
  const companiesBody = document.getElementById("companiesBody");
  const personasBody = document.getElementById("personasBody");
  const companiesCount = document.getElementById("companiesCount");
  const personasCount = document.getElementById("personasCount");
  const declineBtn = document.getElementById("declineBtn");
  const selectApprovedBtn = document.getElementById("selectApprovedBtn");
  const selectAllCompanies = document.getElementById("selectAllCompanies");
  const autoPoll = document.getElementById("autoPoll");
  const pollLabel = document.getElementById("pollLabel");
  const statStatus = document.getElementById("statStatus");
  const statStage = document.getElementById("statStage");
  const statPackages = document.getElementById("statPackages");
  const statArtifacts = document.getElementById("statArtifacts");
  const statusMessage = document.getElementById("statusMessage");
  const statusError = document.getElementById("statusError");
  const stageTrack = document.getElementById("stageTrack");
  const artifactsBody = document.getElementById("artifactsBody");

  if (apiBaseLabel) apiBaseLabel.textContent = API_BASE;

  const savedId = localStorage.getItem("ai_outbound_campaign_id");
  if (savedId && campaignInput) campaignInput.value = savedId;

  let lastCompanies = [];
  let pollTimer = null;
  let lastCampaignSnapshot = null;

  function setStatus(kind, label) {
    statusPill.className = "status-pill" + (kind ? ` is-${kind}` : "");
    statusPill.textContent = label;
  }

  function showResult(text) {
    result.textContent = text;
  }

  function getCampaignId() {
    return (campaignInput.value || "").trim();
  }

  function rememberCampaignId(id) {
    if (id) localStorage.setItem("ai_outbound_campaign_id", id);
  }

  function escapeHtml(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function statusClass(status) {
    const s = String(status || "approved").toLowerCase();
    if (s === "declined" || s === "rejected" || s === "failed") return "badge-err";
    if (s === "approved" || s === "completed") return "badge-ok";
    if (s === "running") return "badge-warm";
    return "badge-muted";
  }

  function isDeclined(status) {
    const s = String(status || "approved").toLowerCase();
    return s === "declined" || s === "rejected";
  }

  function isTerminalCampaign(status, stage) {
    const s = String(status || "").toLowerCase();
    const st = String(stage || "").toLowerCase();
    if (s === "failed" || st === "failed") return true;
    if (s === "completed") return true;
    if (st === "package_ready" || st.startsWith("outreach_")) return true;
    return false;
  }

  function isRunningCampaign(status, stage) {
    if (isTerminalCampaign(status, stage)) return false;
    const s = String(status || "").toLowerCase();
    return s === "running" || s === "pending" || s === "created" || !s;
  }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
    pollLabel.textContent = "Not polling";
    pollLabel.classList.remove("is-live");
  }

  function startPolling() {
    stopPolling();
    if (!autoPoll.checked) return;
    const id = getCampaignId();
    if (!id) return;
    pollLabel.textContent = "Polling…";
    pollLabel.classList.add("is-live");
    pollTimer = setInterval(() => {
      refreshStatus({ silent: true });
    }, POLL_MS);
  }

  function ensurePolling(status, stage) {
    if (autoPoll.checked && isRunningCampaign(status, stage)) {
      if (!pollTimer) startPolling();
      else {
        pollLabel.textContent = "Polling…";
        pollLabel.classList.add("is-live");
      }
    } else {
      stopPolling();
    }
  }

  function artifactSummary(artifact) {
    const payload = artifact.payload || artifact.payload_json || {};
    if (typeof payload === "string") {
      try {
        return artifactSummary({ payload: JSON.parse(payload) });
      } catch {
        return payload.slice(0, 120);
      }
    }
    if (payload.error) return `error: ${payload.error}`;
    if (payload.message) return String(payload.message);
    if (Array.isArray(payload.ranked_companies))
      return `${payload.ranked_companies.length} ranked companies`;
    if (Array.isArray(payload.ranked_personas))
      return `${payload.ranked_personas.length} ranked personas`;
    if (payload.status) return `status=${payload.status}`;
    const keys = Object.keys(payload);
    return keys.length ? `keys: ${keys.slice(0, 6).join(", ")}` : "—";
  }

  function renderStageTrack(currentStage) {
    const current = String(currentStage || "").toLowerCase();
    const idx = PHASE_A_STAGES.indexOf(current);
    const failed = current === "failed";
    stageTrack.innerHTML = PHASE_A_STAGES.map((stage, i) => {
      let cls = "stage-step";
      if (failed) cls += i === 0 ? "" : "";
      else if (idx < 0) cls += "";
      else if (i < idx) cls += " is-done";
      else if (i === idx) cls += " is-current";
      return `<span class="${cls}" title="${escapeHtml(stage)}">${escapeHtml(stage.replace(/_/g, " "))}</span>`;
    }).join("");
    if (failed) {
      stageTrack.insertAdjacentHTML(
        "beforeend",
        `<span class="stage-step is-failed">failed</span>`
      );
    }
  }

  function renderStatus(data) {
    lastCampaignSnapshot = data;
    const c = data.campaign || {};
    const artifacts = data.artifacts || [];
    const packages = data.packages || [];
    const status = c.status || "—";
    const stage = c.stage || "—";

    statStatus.innerHTML = `<span class="row-badge ${statusClass(status)}">${escapeHtml(status)}</span>`;
    statStage.textContent = stage;
    statPackages.textContent = String(packages.length);
    statArtifacts.textContent = String(artifacts.length);

    if (c.error) {
      statusError.hidden = false;
      statusError.textContent = c.error;
    } else {
      statusError.hidden = true;
      statusError.textContent = "";
    }

    if (isTerminalCampaign(status, stage)) {
      if (String(status).toLowerCase() === "failed" || stage === "failed") {
        statusMessage.textContent = "Phase A failed. Check the error and artifacts below.";
      } else {
        statusMessage.textContent =
          "Campaign is ready. You can list companies and personas below.";
      }
    } else if (isRunningCampaign(status, stage)) {
      statusMessage.textContent = `Phase A in progress (stage: ${stage}). Auto-poll refreshes every ${POLL_MS / 1000}s.`;
    } else {
      statusMessage.textContent = `status=${status}, stage=${stage}`;
    }

    renderStageTrack(stage);

    if (!artifacts.length) {
      artifactsBody.innerHTML = `<tr class="empty-row"><td colspan="3">No artifacts yet.</td></tr>`;
    } else {
      const sorted = [...artifacts].sort((a, b) =>
        String(a.created_at || "").localeCompare(String(b.created_at || ""))
      );
      artifactsBody.innerHTML = sorted
        .map(
          (a) => `<tr>
            <td><strong>${escapeHtml(a.stage || "—")}</strong></td>
            <td class="mono dim">${escapeHtml(a.created_at || "—")}</td>
            <td>${escapeHtml(artifactSummary(a))}</td>
          </tr>`
        )
        .join("");
    }

    ensurePolling(status, stage);
  }

  async function refreshStatus({ silent } = {}) {
    const id = getCampaignId();
    if (!id) {
      if (!silent) {
        setStatus("err", "Missing id");
        showResult("Enter a campaign_id first (from Start campaign response).");
      }
      return null;
    }
    rememberCampaignId(id);
    if (!silent) setStatus("pending", "Status…");
    try {
      const res = await getCampaign(id);
      if (!silent || !res.ok) showResult(formatResponse(res));
      else {
        const c = res.data.campaign || {};
        showResult(
          `Polled ${new Date().toLocaleTimeString()} — status=${c.status} stage=${c.stage}\n` +
            formatResponse(res)
        );
      }
      if (res.ok) {
        renderStatus(res.data);
        const c = res.data.campaign || {};
        if (isTerminalCampaign(c.status, c.stage)) {
          setStatus(
            String(c.status).toLowerCase() === "failed" || c.stage === "failed"
              ? "err"
              : "ok",
            c.stage || c.status
          );
        } else {
          setStatus("pending", c.stage || "running");
        }
      } else {
        setStatus("err", `Error ${res.status}`);
        stopPolling();
      }
      return res;
    } catch (err) {
      setStatus("err", "Failed");
      showResult(`Request failed: ${err}\n\nIs the API running at ${API_BASE}?`);
      stopPolling();
      return null;
    }
  }

  function selectedCompanyIds() {
    return Array.from(document.querySelectorAll(".company-check:checked")).map(
      (el) => el.value
    );
  }

  function syncDeclineUi() {
    const ids = selectedCompanyIds();
    const hasApproved = lastCompanies.some((c) => !isDeclined(c.status));
    declineBtn.disabled = ids.length === 0;
    declineBtn.textContent =
      ids.length > 0 ? `Decline selected (${ids.length})` : "Decline selected";
    selectApprovedBtn.disabled = !hasApproved;
    selectAllCompanies.disabled = !hasApproved;
    if (!hasApproved) selectAllCompanies.checked = false;
  }

  function renderCompanies(companies) {
    lastCompanies = companies || [];
    companiesCount.textContent = String(lastCompanies.length);
    if (!lastCompanies.length) {
      companiesBody.innerHTML = `<tr class="empty-row"><td colspan="5">No companies for this campaign.</td></tr>`;
      selectAllCompanies.checked = false;
      syncDeclineUi();
      return;
    }
    companiesBody.innerHTML = lastCompanies
      .map((c) => {
        const declined = isDeclined(c.status);
        const check = declined
          ? `<input type="checkbox" disabled title="Already declined" aria-label="Already declined" />`
          : `<input type="checkbox" class="company-check" value="${escapeHtml(c.id)}" aria-label="Select ${escapeHtml(c.company_name)}" />`;
        return `<tr class="${declined ? "row-declined" : ""}">
          <td class="col-check">${check}</td>
          <td><strong>${escapeHtml(c.company_name)}</strong></td>
          <td><span class="row-badge ${statusClass(c.status)}">${escapeHtml(c.status || "approved")}</span></td>
          <td class="mono">${escapeHtml(c.apollo_company_id)}</td>
          <td class="mono dim">${escapeHtml(c.id)}</td>
        </tr>`;
      })
      .join("");
    selectAllCompanies.checked = false;
    syncDeclineUi();
  }

  function renderPersonas(personas) {
    personasCount.textContent = String(personas.length);
    if (!personas.length) {
      personasBody.innerHTML = `<tr class="empty-row"><td colspan="5">No personas for this campaign.</td></tr>`;
      return;
    }
    personasBody.innerHTML = personas
      .map((p) => {
        const score =
          p.persona_score != null && p.persona_score !== ""
            ? Number(p.persona_score).toFixed(3)
            : "—";
        const li = p.linkedin_url
          ? `<a href="${escapeHtml(p.linkedin_url)}" target="_blank" rel="noopener">${escapeHtml(p.linkedin_url)}</a>`
          : "—";
        return `<tr>
          <td><strong>${escapeHtml(p.persona_name)}</strong></td>
          <td class="mono">${escapeHtml(score)}</td>
          <td class="link-cell">${li}</td>
          <td class="mono">${escapeHtml(p.apollo_company_id)}</td>
          <td class="mono dim">${escapeHtml(p.apollo_persona_id)}</td>
        </tr>`;
      })
      .join("");
  }

  async function loadCompanies() {
    const id = getCampaignId();
    if (!id) {
      setStatus("err", "Missing id");
      showResult("Enter a campaign_id first (from Start campaign response).");
      return null;
    }
    rememberCampaignId(id);
    setStatus("pending", "Companies…");
    try {
      const res = await listCampaignCompanies(id);
      showResult(formatResponse(res));
      if (res.ok) {
        renderCompanies(res.data.companies || []);
        setStatus("ok", `${res.data.count ?? 0} companies`);
      } else {
        setStatus("err", `Error ${res.status}`);
      }
      return res;
    } catch (err) {
      setStatus("err", "Failed");
      showResult(`Request failed: ${err}\n\nIs the API running at ${API_BASE}?`);
      return null;
    }
  }

  async function loadPersonas() {
    const id = getCampaignId();
    if (!id) {
      setStatus("err", "Missing id");
      showResult("Enter a campaign_id first (from Start campaign response).");
      return null;
    }
    rememberCampaignId(id);
    setStatus("pending", "Personas…");
    try {
      const res = await listCampaignPersonas(id);
      showResult(formatResponse(res));
      if (res.ok) {
        renderPersonas(res.data.personas || []);
        setStatus("ok", `${res.data.count ?? 0} personas`);
      } else {
        setStatus("err", `Error ${res.status}`);
      }
      return res;
    } catch (err) {
      setStatus("err", "Failed");
      showResult(`Request failed: ${err}\n\nIs the API running at ${API_BASE}?`);
      return null;
    }
  }

  async function declineSelected() {
    const id = getCampaignId();
    const companyIds = selectedCompanyIds();
    if (!id) {
      setStatus("err", "Missing id");
      showResult("Enter a campaign_id first.");
      return;
    }
    if (!companyIds.length) {
      setStatus("err", "None selected");
      showResult("Select at least one approved company to decline.");
      return;
    }

    const names = lastCompanies
      .filter((c) => companyIds.includes(c.id))
      .map((c) => c.company_name)
      .join(", ");
    if (
      !window.confirm(
        `Decline ${companyIds.length} compan${companyIds.length === 1 ? "y" : "ies"}?\n\n${names}`
      )
    ) {
      return;
    }

    rememberCampaignId(id);
    setStatus("pending", "Declining…");
    declineBtn.disabled = true;
    try {
      const res = await declineCampaignCompanies(id, companyIds);
      showResult(formatResponse(res));
      if (res.ok) {
        setStatus("ok", res.data.message || "Declined");
        await loadCompanies();
      } else {
        setStatus("err", `Error ${res.status}`);
        syncDeclineUi();
      }
    } catch (err) {
      setStatus("err", "Failed");
      showResult(`Request failed: ${err}`);
      syncDeclineUi();
    }
  }

  companiesBody.addEventListener("change", (e) => {
    if (e.target.classList.contains("company-check")) syncDeclineUi();
  });

  selectAllCompanies.addEventListener("change", () => {
    const on = selectAllCompanies.checked;
    document.querySelectorAll(".company-check").forEach((el) => {
      el.checked = on;
    });
    syncDeclineUi();
  });

  selectApprovedBtn.addEventListener("click", () => {
    document.querySelectorAll(".company-check").forEach((el) => {
      el.checked = true;
    });
    selectAllCompanies.checked = document.querySelectorAll(".company-check").length > 0;
    syncDeclineUi();
  });

  declineBtn.addEventListener("click", declineSelected);
  document.getElementById("refreshStatusBtn").addEventListener("click", () => refreshStatus());
  document.getElementById("loadCompaniesBtn").addEventListener("click", loadCompanies);
  document.getElementById("loadPersonasBtn").addEventListener("click", loadPersonas);

  autoPoll.addEventListener("change", () => {
    if (!autoPoll.checked) {
      stopPolling();
      return;
    }
    const c = lastCampaignSnapshot && lastCampaignSnapshot.campaign;
    if (c && isRunningCampaign(c.status, c.stage)) startPolling();
    else if (getCampaignId()) refreshStatus();
  });

  campaignInput.addEventListener("change", stopPolling);

  document.getElementById("loadBothBtn").addEventListener("click", async () => {
    const id = getCampaignId();
    if (!id) {
      setStatus("err", "Missing id");
      showResult("Enter a campaign_id first.");
      return;
    }
    rememberCampaignId(id);
    setStatus("pending", "Loading…");
    try {
      const [cRes, pRes] = await Promise.all([
        listCampaignCompanies(id),
        listCampaignPersonas(id),
      ]);
      if (cRes.ok) renderCompanies(cRes.data.companies || []);
      if (pRes.ok) renderPersonas(pRes.data.personas || []);
      showResult(
        `Companies:\n${formatResponse(cRes)}\n\nPersonas:\n${formatResponse(pRes)}`
      );
      const ok = cRes.ok && pRes.ok;
      setStatus(
        ok ? "ok" : "err",
        ok
          ? `${cRes.data.count ?? 0} cos · ${pRes.data.count ?? 0} personas`
          : "Partial error"
      );
    } catch (err) {
      setStatus("err", "Failed");
      showResult(`Request failed: ${err}`);
    }
  });

  // Auto-load status if we already have a campaign id
  if (getCampaignId()) {
    refreshStatus();
  }
})();
