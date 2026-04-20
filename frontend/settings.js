(function () {
  "use strict";

  const API_BASE = "/api";

  function getJson(url, options = {}) {
    return fetch(url, {
      ...options,
      headers: { "Content-Type": "application/json", ...options.headers },
    }).then((r) => {
      if (!r.ok) {
        return r.text().then((text) => {
          let msg = r.statusText;
          try {
            const d = JSON.parse(text);
            if (d.detail) msg = typeof d.detail === "string" ? d.detail : JSON.stringify(d.detail);
          } catch (_) {
            if (text) msg = text.slice(0, 200);
          }
          return Promise.reject(new Error(msg));
        });
      }
      return r.json();
    });
  }

  function postJson(url, body) {
    return getJson(url, {
      method: "POST",
      body: JSON.stringify(body || {}),
    });
  }

  function showMessage(el, text, type) {
    if (!el) return;
    el.textContent = text;
    el.className = "message " + (type === "error" ? "error" : "success");
    el.hidden = false;
  }

  function hideMessage(el) {
    if (!el) return;
    el.hidden = true;
  }

  function setInputValue(id, value) {
    var el = document.getElementById(id);
    if (!el) return;
    el.value = value == null ? "" : String(value);
  }

  const btnSystemSettingsSave = document.getElementById("btn-system-settings-save");
  const btnExchangeToken = document.getElementById("btn-exchange-token");
  const systemSettingsMessage = document.getElementById("system-settings-message");
  const exchangeTokenMessage = document.getElementById("exchange-token-message");
  const selectedAccountTitle = document.getElementById("selected-account-title");
  const adminEnvSection = document.getElementById("admin-env-section");
  const urlParams = new URLSearchParams(window.location.search || "");
  const isNewAccountMode = urlParams.get("new_account") === "1";
  const selectedAccountId = (urlParams.get("account_id") || localStorage.getItem("autosocial_active_account_id") || "").trim();

  function readSystemSettingsPayload() {
    var payload = {
      account: {
        id: (document.getElementById("setting-account-id") || {}).value || selectedAccountId || null,
        ig_user_id: (document.getElementById("setting-account-ig-user-id") || {}).value || "",
        access_token: (document.getElementById("setting-account-access-token") || {}).value || "",
        niche: (document.getElementById("setting-account-niche") || {}).value || "",
        force_create: isNewAccountMode,
      },
    };
    if (adminEnvSection && !adminEnvSection.hidden) {
      payload.env = {
        OPENAI_API_KEY: (document.getElementById("setting-openai-api-key") || {}).value || "",
        INSTAGRAM_APP_ID: (document.getElementById("setting-instagram-app-id") || {}).value || "",
        INSTAGRAM_APP_SECRET: (document.getElementById("setting-instagram-app-secret") || {}).value || "",
        INSTAGRAM_ACCESS_TOKEN: (document.getElementById("setting-instagram-access-token") || {}).value || "",
        INSTAGRAM_USER_ID: (document.getElementById("setting-instagram-ig-user-id") || {}).value || "",
        BASE_URL: (document.getElementById("setting-base-url") || {}).value || "",
        UPLOAD_API_URL: (document.getElementById("setting-upload-api-url") || {}).value || "",
        UPLOAD_API_KEY: (document.getElementById("setting-upload-api-key") || {}).value || "",
        UPLOAD_BASE_URL: (document.getElementById("setting-upload-base-url") || {}).value || "",
        R2_PUBLIC_BASE_URL: (document.getElementById("setting-r2-public-base-url") || {}).value || "",
      };
    }
    return payload;
  }

  function fillSystemSettingsForm(data) {
    var env = (data && data.env) || {};
    var account = (data && data.account) || {};
    var isAdmin = !!(data && data.is_admin);
    if (adminEnvSection) adminEnvSection.hidden = !isAdmin;
    setInputValue("setting-openai-api-key", env.OPENAI_API_KEY || "");
    setInputValue("setting-instagram-app-id", env.INSTAGRAM_APP_ID || "");
    setInputValue("setting-instagram-app-secret", env.INSTAGRAM_APP_SECRET || "");
    setInputValue("setting-instagram-access-token", env.INSTAGRAM_ACCESS_TOKEN || "");
    setInputValue("setting-instagram-ig-user-id", env.INSTAGRAM_USER_ID || "");
    setInputValue("setting-base-url", env.BASE_URL || "");
    setInputValue("setting-upload-api-url", env.UPLOAD_API_URL || "");
    setInputValue("setting-upload-api-key", env.UPLOAD_API_KEY || "");
    setInputValue("setting-upload-base-url", env.UPLOAD_BASE_URL || "");
    setInputValue("setting-r2-public-base-url", env.R2_PUBLIC_BASE_URL || "");
    setInputValue("setting-account-id", account.id || "");
    setInputValue("setting-account-ig-user-id", account.ig_user_id || "");
    setInputValue("setting-account-access-token", account.access_token || "");
    setInputValue("setting-account-niche", account.niche || "");
    if (selectedAccountTitle) {
      var t = account.id ? "Seçili Hesap (DB) • ID " + account.id : "Seçili Hesap (DB)";
      if (isAdmin) t += " • Ana-Admin";
      selectedAccountTitle.textContent = t;
    }
  }

  function loadSystemSettings() {
    if (isNewAccountMode) {
      setInputValue("setting-account-id", "");
      setInputValue("setting-account-ig-user-id", "");
      setInputValue("setting-account-access-token", "");
      setInputValue("setting-account-niche", "");
      if (adminEnvSection) adminEnvSection.hidden = true;
      if (selectedAccountTitle) selectedAccountTitle.textContent = "Yeni Hesap (DB)";
      showMessage(systemSettingsMessage, "Yeni hesap modu: alanlar boş başlatıldı.", "success");
      return;
    }
    hideMessage(systemSettingsMessage);
    var url = API_BASE + "/settings/system";
    if (selectedAccountId) url += "?account_id=" + encodeURIComponent(selectedAccountId);
    getJson(url)
      .then(function (res) {
        fillSystemSettingsForm(res || {});
      })
      .catch(function (err) {
        showMessage(systemSettingsMessage, err.message || "Sistem ayarları yüklenemedi.", "error");
      });
  }

  function saveSystemSettings() {
    if (!btnSystemSettingsSave) return;
    hideMessage(systemSettingsMessage);
    btnSystemSettingsSave.disabled = true;
    var url = API_BASE + "/settings/system";
    if (selectedAccountId && !isNewAccountMode) url += "?account_id=" + encodeURIComponent(selectedAccountId);
    postJson(url, readSystemSettingsPayload())
      .then(function (res) {
        fillSystemSettingsForm(res || {});
        showMessage(systemSettingsMessage, "Sistem ayarları kaydedildi.", "success");
      })
      .catch(function (err) {
        showMessage(systemSettingsMessage, err.message || "Sistem ayarları kaydedilemedi.", "error");
      })
      .finally(function () {
        btnSystemSettingsSave.disabled = false;
      });
  }

  function exchangeShortToken() {
    hideMessage(exchangeTokenMessage);
    const accountId = (document.getElementById("setting-account-id") || {}).value || selectedAccountId || "";
    const shortToken = (document.getElementById("setting-short-access-token") || {}).value || "";
    if (!accountId) {
      showMessage(exchangeTokenMessage, "Önce bir hesap seçin.", "error");
      return;
    }
    if (!shortToken.trim()) {
      showMessage(exchangeTokenMessage, "Kısa access token girin.", "error");
      return;
    }
    if (btnExchangeToken) btnExchangeToken.disabled = true;
    postJson(API_BASE + "/settings/exchange-token", {
      account_id: Number(accountId),
      short_token: shortToken.trim(),
    })
      .then(function (res) {
        const msg =
          "Long token güncellendi. Hesap ID: " +
          (res.account_id || accountId) +
          " • Token: " +
          (res.long_token_masked || "") +
          (res.expires_in ? " • expires_in: " + res.expires_in : "");
        showMessage(exchangeTokenMessage, msg, "success");
        setInputValue("setting-short-access-token", "");
        loadSystemSettings();
      })
      .catch(function (err) {
        showMessage(exchangeTokenMessage, err.message || "Token exchange başarısız.", "error");
      })
      .finally(function () {
        if (btnExchangeToken) btnExchangeToken.disabled = false;
      });
  }

  if (btnSystemSettingsSave) {
    btnSystemSettingsSave.addEventListener("click", saveSystemSettings);
  }
  if (btnExchangeToken) {
    btnExchangeToken.addEventListener("click", exchangeShortToken);
  }

  loadSystemSettings();
})();
