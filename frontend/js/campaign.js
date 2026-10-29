/** AI Outbound — Campaign Studio */
(function () {
  const form = document.getElementById("form");
  const result = document.getElementById("result");
  const statusPill = document.getElementById("statusPill");
  const apiBaseLabel = document.getElementById("apiBaseLabel");

  if (apiBaseLabel) apiBaseLabel.textContent = API_BASE;

  const WEIGHT_KEYS = [
    "industry_weight",
    "size_weight",
    "revenue_weight",
    "tech_stack_weight",
    "firmographic_weight",
    "intent_weight",
    "fit_weight",
    "reachability_weight",
    "timing_weight",
    "functional_weight",
    "authority_weight",
    "engagement_weight",
  ];

  const SAMPLE = {
    user_id: "test-user-1",
    icp_description_text:
      "We sell NudgeShield cyber-risk analytics to mid-market insurance and financial services companies in the United States. Contact risk, underwriting, and revenue leaders.\n\n" +
      "- Industry: Insurance, Financial Services, Banking, Fintech\n" +
      "- Company size: 200 to 5000 employees\n" +
      "- Located in: United States\n\n" +
      "- Annual revenue / ARR: $10,000,000 to $500,000,000\n" +
      "- Preferred cities: San Francisco (United States), New York (United States), Austin (United States)\n" +
      "- Tech stack: Guidewire, Salesforce, Snowflake, AWS, Tableau, Slack\n" +
      "- Growth stage: growth stage\n" +
      "- Funding stage: Series B, Series C, or later\n\n" +
      "Exclude:\n" +
      "- Industries: Gambling, Government, Non-profit, Software\n" +
      "- Keywords: agency, staffing, consulting-only, competitor\n" +
      "- Company size under 50 employees\n\n" +
      "Target roles:\n" +
      "- VP of Sales\n" +
      "- Head of Sales\n" +
      "- Director of Sales\n" +
      "- Chief Revenue Officer\n" +
      "- Head of Revenue Operations\n" +
      "- Sales Operations Manager",
    user_offering:
      "NudgeShield is a cyber-risk and underwriting intelligence platform that helps insurers and financial institutions detect emerging threats, score account risk, and prioritize high-intent commercial opportunities.",
    blacklist: { companies: ["Gitlab"], personas: [] },
    configurable_weights: {
      industry_weight: 0.5,
      size_weight: 0.3,
      revenue_weight: 0.1,
      tech_stack_weight: 0.1,
      firmographic_weight: 0.6,
      intent_weight: 0.4,
      fit_weight: 0.7,
      reachability_weight: 0.2,
      timing_weight: 0.1,
      functional_weight: 0.6,
      authority_weight: 0.4,
      engagement_weight: 40.0,
    },
    company_limit: 6,
    run_async: true,
    auto_start_outreach: false,
    sender_company: "NudgeShield",
    sender_elevator_pitch:
      "We help insurers and financial institutions detect emerging cyber threats and prioritize high-intent commercial opportunities.",
    offer_name: "Cyber-Risk Audit",
    solution_summary: "Quick cyber-risk and underwriting intelligence snapshot",
    cta: "Reply to book a 15-minute call",
    approval_mode: "per_sequence",
    use_native_language: false,
    message_language: "en",
    has_inmail_credits: false,
    debug_mode: true,
  };

  function setStatus(kind, label) {
    statusPill.className = "status-pill" + (kind ? ` is-${kind}` : "");
    statusPill.textContent = label;
  }

  function showResult(text) {
    result.textContent = text;
  }

  function linesToList(id) {
    return document
      .getElementById(id)
      .value.split(/\r?\n/)
      .map((s) => s.trim())
      .filter(Boolean);
  }

  function listToLines(arr) {
    return (arr || []).join("\n");
  }

  function numVal(id) {
    const el = document.getElementById(id);
    if (!el || el.value === "") return undefined;
    return Number(el.value);
  }

  function buildWeights() {
    const weights = {};
    WEIGHT_KEYS.forEach((key) => {
      const v = numVal(`w_${key}`);
      if (v !== undefined && !Number.isNaN(v)) weights[key] = v;
    });
    return weights;
  }

  function buildBody() {
    return {
      user_id: document.getElementById("user_id").value.trim(),
      icp_description_text: document.getElementById("icp_description_text").value,
      user_offering: document.getElementById("user_offering").value.trim(),
      blacklist: {
        companies: linesToList("blacklist_companies"),
        personas: linesToList("blacklist_personas"),
      },
      configurable_weights: buildWeights(),
      company_limit: numVal("company_limit"),
      run_async: document.getElementById("run_async").checked,
      auto_start_outreach: document.getElementById("auto_start_outreach").checked,
      sender_company: document.getElementById("sender_company").value.trim(),
      sender_elevator_pitch: document.getElementById("sender_elevator_pitch").value.trim(),
      offer_name: document.getElementById("offer_name").value.trim(),
      solution_summary: document.getElementById("solution_summary").value.trim(),
      cta: document.getElementById("cta").value.trim(),
      approval_mode: document.getElementById("approval_mode").value,
      use_native_language: document.getElementById("use_native_language").checked,
      message_language: document.getElementById("message_language").value.trim(),
      has_inmail_credits: document.getElementById("has_inmail_credits").checked,
      debug_mode: document.getElementById("debug_mode").checked,
    };
  }

  /** PATCH body: same fields without user_id (user_id is in the URL). */
  function buildPatchBody() {
    const body = buildBody();
    delete body.user_id;
    return body;
  }

  function fillForm(p) {
    if (!p) return;
    if (p.user_id != null) document.getElementById("user_id").value = p.user_id;
    if (p.icp_description_text != null) document.getElementById("icp_description_text").value = p.icp_description_text;
    if (p.user_offering != null) document.getElementById("user_offering").value = p.user_offering;
    if (p.company_limit != null) document.getElementById("company_limit").value = p.company_limit;
    if (p.run_async != null) document.getElementById("run_async").checked = !!p.run_async;
    if (p.auto_start_outreach != null) document.getElementById("auto_start_outreach").checked = !!p.auto_start_outreach;

    const bl = p.blacklist || {};
    document.getElementById("blacklist_companies").value = listToLines(bl.companies);
    document.getElementById("blacklist_personas").value = listToLines(bl.personas);

    const w = p.configurable_weights || {};
    WEIGHT_KEYS.forEach((key) => {
      if (w[key] != null) document.getElementById(`w_${key}`).value = w[key];
    });

    if (p.sender_company != null) document.getElementById("sender_company").value = p.sender_company;
    if (p.sender_elevator_pitch != null) document.getElementById("sender_elevator_pitch").value = p.sender_elevator_pitch;
    if (p.offer_name != null) document.getElementById("offer_name").value = p.offer_name;
    if (p.solution_summary != null) document.getElementById("solution_summary").value = p.solution_summary;
    if (p.cta != null) document.getElementById("cta").value = p.cta;
    if (p.approval_mode != null) document.getElementById("approval_mode").value = p.approval_mode;
    if (p.message_language != null) document.getElementById("message_language").value = p.message_language;
    if (p.use_native_language != null) document.getElementById("use_native_language").checked = !!p.use_native_language;
    if (p.has_inmail_credits != null) document.getElementById("has_inmail_credits").checked = !!p.has_inmail_credits;
    if (p.debug_mode != null) document.getElementById("debug_mode").checked = !!p.debug_mode;
  }

  // Tabs
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      const name = tab.dataset.tab;
      document.querySelectorAll(".tab").forEach((t) => {
        t.classList.toggle("is-active", t === tab);
        t.setAttribute("aria-selected", t === tab ? "true" : "false");
      });
      document.querySelectorAll(".tab-panel").forEach((panel) => {
        const active = panel.id === `panel-${name}`;
        panel.classList.toggle("is-active", active);
        panel.hidden = !active;
      });
    });
  });

  document.getElementById("sampleBtn").addEventListener("click", () => {
    fillForm(SAMPLE);
    setStatus("", "Sample loaded");
    showResult("Form reset to NudgeShield sample payload.");
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = buildBody();
    if (!body.user_id) {
      setStatus("err", "Missing user");
      showResult("user_id is required");
      return;
    }

    setStatus("pending", "Saving…");
    showResult("Sending POST…\n\n" + JSON.stringify(body, null, 2));
    document.getElementById("saveBtn").disabled = true;
    try {
      const res = await saveCampaignParams(body);
      showResult(formatResponse(res));
      setStatus(res.ok ? "ok" : "err", res.ok ? "Saved" : `Error ${res.status}`);
    } catch (err) {
      setStatus("err", "Failed");
      showResult(`Request failed: ${err}\n\nIs the API running at ${API_BASE}?`);
    } finally {
      document.getElementById("saveBtn").disabled = false;
    }
  });

  document.getElementById("patchBtn").addEventListener("click", async () => {
    const userId = document.getElementById("user_id").value.trim();
    if (!userId) {
      setStatus("err", "Missing user");
      showResult("user_id is required");
      return;
    }
    const body = buildPatchBody();
    setStatus("pending", "Patching…");
    showResult("Sending PATCH…\n\n" + JSON.stringify(body, null, 2));
    const btn = document.getElementById("patchBtn");
    btn.disabled = true;
    try {
      const res = await updateCampaignParams(userId, body);
      showResult(formatResponse(res));
      setStatus(res.ok ? "ok" : "err", res.ok ? "Updated" : `Error ${res.status}`);
      if (res.ok && res.data && res.data.params) {
        fillForm({ ...res.data.params, user_id: res.data.user_id || userId });
      }
      if (!res.ok && res.status === 404) {
        showResult(
          formatResponse(res) +
            "\n\nNo draft exists yet for this user_id. Use Save params (POST) first."
        );
      }
    } catch (err) {
      setStatus("err", "Failed");
      showResult(`Request failed: ${err}\n\nIs the API running at ${API_BASE}?`);
    } finally {
      btn.disabled = false;
    }
  });

  document.getElementById("loadBtn").addEventListener("click", async () => {
    const userId = document.getElementById("user_id").value.trim();
    if (!userId) {
      setStatus("err", "Missing user");
      showResult("Enter a user_id first");
      return;
    }
    setStatus("pending", "Loading…");
    showResult("Loading…");
    try {
      const res = await getCampaignParams(userId);
      showResult(formatResponse(res));
      setStatus(res.ok ? "ok" : "err", res.ok ? "Loaded" : `Error ${res.status}`);
      if (res.ok && res.data && res.data.params) {
        fillForm({ ...res.data.params, user_id: res.data.user_id || userId });
      }
    } catch (err) {
      setStatus("err", "Failed");
      showResult(`Request failed: ${err}`);
    }
  });

  document.getElementById("startBtn").addEventListener("click", async () => {
    const userId = document.getElementById("user_id").value.trim();
    if (!userId) {
      setStatus("err", "Missing user");
      showResult("Enter a user_id first");
      return;
    }
    setStatus("pending", "Starting…");
    showResult("Starting campaign…");
    try {
      const res = await startCampaign(userId);
      showResult(formatResponse(res));
      setStatus(res.ok ? "ok" : "err", res.ok ? "Started" : `Error ${res.status}`);
      if (res.ok && res.data && res.data.campaign_id) {
        localStorage.setItem("ai_outbound_campaign_id", res.data.campaign_id);
        showResult(
          formatResponse(res) +
            `\n\n→ Open Results to poll status & list companies/personas:\nresults.html (campaign_id saved)`
        );
      }
    } catch (err) {
      setStatus("err", "Failed");
      showResult(`Request failed: ${err}`);
    }
  });
})();
