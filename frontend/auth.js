/**
 * AutoSocial AI — Auth helper (tüm sayfalarda yüklenir).
 *
 * Kullanım:
 *   window.AuthAPI.login(email, password) -> Promise
 *   window.AuthAPI.register(email, password, fullName) -> Promise
 *   window.AuthAPI.logout()
 *   window.AuthAPI.getToken()
 *   window.AuthAPI.requireAuth() // korumalı sayfaların tepesinde çağır
 *   window.AuthAPI.apiFetch(url, opts) // Authorization header otomatik
 *   window.AuthAPI.currentUser() -> Promise<User>
 */
(function () {
  "use strict";

  const ACCESS_KEY = "autosocial_access_token";
  const REFRESH_KEY = "autosocial_refresh_token";
  const USER_KEY = "autosocial_user";

  function getToken() {
    try { return localStorage.getItem(ACCESS_KEY) || ""; } catch (_) { return ""; }
  }
  function getRefreshToken() {
    try { return localStorage.getItem(REFRESH_KEY) || ""; } catch (_) { return ""; }
  }
  function setTokens(access, refresh) {
    try {
      if (access) localStorage.setItem(ACCESS_KEY, access);
      if (refresh) localStorage.setItem(REFRESH_KEY, refresh);
    } catch (_) {}
  }
  function clearTokens() {
    try {
      localStorage.removeItem(ACCESS_KEY);
      localStorage.removeItem(REFRESH_KEY);
      localStorage.removeItem(USER_KEY);
    } catch (_) {}
  }
  function setUser(u) { try { localStorage.setItem(USER_KEY, JSON.stringify(u || null)); } catch (_) {} }
  function getUser() {
    try { const s = localStorage.getItem(USER_KEY); return s ? JSON.parse(s) : null; } catch (_) { return null; }
  }

  function parseJson(response) {
    return response.text().then(function (txt) {
      if (!txt) return null;
      try { return JSON.parse(txt); } catch (_) { return { raw: txt }; }
    });
  }

  function raiseIfError(response) {
    if (response.ok) return response;
    return parseJson(response).then(function (data) {
      let msg = response.statusText || "İstek başarısız.";
      if (data && data.detail) msg = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
      const err = new Error(msg);
      err.status = response.status;
      err.data = data;
      throw err;
    });
  }

  function login(email, password) {
    return fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: email, password: password }),
    })
      .then(raiseIfError)
      .then((r) => r.json())
      .then((data) => {
        setTokens(data.access_token, data.refresh_token);
        return currentUser().catch(() => null);
      });
  }

  function registerUser(email, password, fullName) {
    return fetch("/api/auth/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: email, password: password, full_name: fullName || null }),
    })
      .then(raiseIfError)
      .then((r) => r.json())
      .then((data) => {
        setTokens(data.access_token, data.refresh_token);
        return currentUser().catch(() => null);
      });
  }

  function logout() {
    const tok = getToken();
    const p = tok
      ? fetch("/api/auth/logout", { method: "POST", headers: authHeaders() }).catch(() => null)
      : Promise.resolve();
    return p.finally(() => {
      clearTokens();
      window.location.href = "/login";
    });
  }

  function authHeaders() {
    const t = getToken();
    return t ? { Authorization: "Bearer " + t } : {};
  }

  function refreshAccessToken() {
    const rt = getRefreshToken();
    if (!rt) return Promise.reject(new Error("no refresh token"));
    return fetch("/api/auth/refresh", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: rt }),
    })
      .then(raiseIfError)
      .then((r) => r.json())
      .then((data) => {
        setTokens(data.access_token, data.refresh_token);
        return data.access_token;
      });
  }

  /**
   * Authorization header otomatik, 401'de refresh + bir kez retry.
   * Dönen Response nesnesi üstünde .ok, .status, .json() vb. standart kullanım yapılır.
   */
  function apiFetch(url, opts) {
    opts = opts || {};
    const headers = Object.assign({}, opts.headers || {}, authHeaders());
    const init = Object.assign({}, opts, { headers: headers });

    return fetch(url, init).then(function (res) {
      if (res.status !== 401) return res;
      // 401: refresh ve tekrar dene
      return refreshAccessToken()
        .then(function () {
          const h2 = Object.assign({}, opts.headers || {}, authHeaders());
          return fetch(url, Object.assign({}, opts, { headers: h2 }));
        })
        .catch(function () {
          clearTokens();
          if (!location.pathname.startsWith("/login")) {
            location.href = "/login?next=" + encodeURIComponent(location.pathname + location.search);
          }
          return res;
        });
    });
  }

  function currentUser() {
    return apiFetch("/api/auth/me").then(function (r) {
      if (!r.ok) throw new Error("auth/me failed");
      return r.json();
    }).then(function (u) { setUser(u); return u; });
  }

  /** Korumalı sayfa guard. Token yoksa login sayfasına yönlendirir. */
  function requireAuth() {
    if (!getToken()) {
      location.href = "/login?next=" + encodeURIComponent(location.pathname + location.search);
      return false;
    }
    // background'da doğrula; geçersizse yönlendir
    currentUser().catch(function () {
      clearTokens();
      location.href = "/login?next=" + encodeURIComponent(location.pathname + location.search);
    });
    return true;
  }

  window.AuthAPI = {
    login: login,
    register: registerUser,
    logout: logout,
    getToken: getToken,
    getUser: getUser,
    currentUser: currentUser,
    apiFetch: apiFetch,
    requireAuth: requireAuth,
    authHeaders: authHeaders,
    clearTokens: clearTokens,
  };

  // ---- Global fetch patch ----
  // /api/* istekleri için Authorization header'ını otomatik ekler.
  // 401 dönerse refresh dener, olmazsa login'e yönlendirir.
  // Auth endpoint'leri (/api/auth/login, /api/auth/register, /api/auth/refresh)
  // kendi header'larını yönetir; patch atlanır.
  const AUTH_SKIP = ["/api/auth/login", "/api/auth/register", "/api/auth/refresh"];
  const originalFetch = window.fetch.bind(window);

  function shouldIntercept(url) {
    try {
      const u = typeof url === "string" ? url : (url && url.url) || "";
      if (!u) return false;
      if (u.indexOf("/api/") === -1) return false;
      for (let i = 0; i < AUTH_SKIP.length; i++) {
        if (u.indexOf(AUTH_SKIP[i]) !== -1) return false;
      }
      return true;
    } catch (_) { return false; }
  }

  window.fetch = function (input, init) {
    init = init || {};
    if (!shouldIntercept(input)) return originalFetch(input, init);

    const baseHeaders = init.headers instanceof Headers
      ? Object.fromEntries(init.headers.entries())
      : (init.headers || {});
    const withAuth = Object.assign({}, baseHeaders, authHeaders());
    const firstInit = Object.assign({}, init, { headers: withAuth });

    return originalFetch(input, firstInit).then(function (res) {
      if (res.status !== 401) return res;
      return refreshAccessToken()
        .then(function () {
          const retryHeaders = Object.assign({}, baseHeaders, authHeaders());
          return originalFetch(input, Object.assign({}, init, { headers: retryHeaders }));
        })
        .catch(function () {
          clearTokens();
          if (!location.pathname.startsWith("/login")) {
            location.href = "/login?next=" + encodeURIComponent(location.pathname + location.search);
          }
          return res;
        });
    });
  };
})();
