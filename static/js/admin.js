/*
 * [권태현 전담] 운영 관리자 화면 프론트엔드
 * 챗봇 화면과 같은 로그인 토큰(localStorage의 access_token)을 쓰고,
 * 관리자 API(/api/admin)에 Authorization: Bearer 헤더를 붙여 요청합니다.
 * 서버에서 받은 글자(질문, 응답, 아이디, 주소 등)는 모두 textContent로 넣어 HTML로 해석되지 않게 합니다.
 */
(() => {
  "use strict";

  // 챗봇 화면(app.js)과 같은 저장 키
  const TOKEN_KEY = "access_token";
  const USERNAME_KEY = "username";
  const ROLE_KEY = "role";
  const ADMIN_ROLE = "admin";
  const PAGE_SIZE = 50;
  const TIME_ZONE = "Asia/Seoul"; // 서버 로그(server.log)와 맞춰 한국 시간으로 표시

  // 오류 코드 → 한국어 설명 (README 오류 코드표와 같음)
  const ERROR_CODE_LABELS = {
    AUTH_REQUIRED: "로그인 필요",
    INVALID_CREDENTIALS: "아이디·비밀번호 불일치",
    ADMIN_REQUIRED: "관리자 아님",
    FORBIDDEN: "권한 없음",
    NOT_FOUND: "없는 주소",
    REQUEST_NOT_FOUND: "요청 ID 기록 없음",
    METHOD_NOT_ALLOWED: "허용되지 않은 요청 방식",
    USERNAME_TAKEN: "아이디 중복",
    VALIDATION_ERROR: "입력값 오류",
    PROMPT_INVALID: "질문 형식 오류",
    INTERNAL_ERROR: "서버 내부 오류",
    AI_TIMEOUT: "AI 응답 시간 초과",
    AI_UPSTREAM_ERROR: "AI 서버 오류",
    AI_BAD_RESPONSE: "AI 응답 형식 오류",
    AI_CONNECTION_ERROR: "AI 연결 실패",
    AI_UNEXPECTED_ERROR: "AI 호출 중 예상 못 한 오류",
    AI_NOT_CONFIGURED: "AI 키 미설정",
  };

  // 대화 로그의 실패 종류(error_type) → 한국어 설명
  const FAILURE_TYPE_LABELS = {
    TIMEOUT: "AI 응답 시간 초과",
    UPSTREAM_ERROR: "AI 서버 오류",
    BAD_RESPONSE: "AI 응답 형식 오류",
    CONNECTION_ERROR: "AI 연결 실패",
    UNEXPECTED_ERROR: "예상 못 한 오류",
    NOT_CONFIGURED: "AI 키 미설정",
    UNKNOWN: "종류 기록 없음 (이전 기록)",
  };

  const $ = (selector) => document.querySelector(selector);
  const adminMain = $("#admin-main");
  const adminAuth = $("#admin-auth");
  const bootStatus = $("#boot-status");
  const loginView = $("#login-view");
  const loginForm = $("#admin-login-form");
  const loginNotice = $("#login-notice");
  const loginMessage = $("#admin-login-message");
  const deniedView = $("#denied-view");
  const deniedText = $("#denied-text");
  const dashboard = $("#dashboard");
  const errorBanner = $("#error-banner");
  const errorBannerText = $("#error-banner-text");
  const tooltip = $("#chart-tooltip");
  const tabs = [...document.querySelectorAll(".admin-tab")];
  const panels = [...document.querySelectorAll(".panel")];

  const overviewContent = $("#overview-content");
  const overviewUpdated = $("#overview-updated");
  const healthStatus = $("#health-status");
  const healthFacts = $("#health-facts");
  const kpiGrid = $("#kpi-grid");
  const failureBars = $("#failure-bars");
  const errorCodeBars = $("#error-code-bars");
  const recentErrorsBody = $("#recent-errors-body");

  const requestsFilter = $("#requests-filter");
  const requestsContent = $("#requests-content");
  const requestsBody = $("#requests-body");
  const requestsRange = $("#requests-range");
  const requestsPrev = $("#requests-prev");
  const requestsNext = $("#requests-next");

  const chatsFilter = $("#chats-filter");
  const chatsContent = $("#chats-content");
  const chatsList = $("#chats-list");
  const chatsRange = $("#chats-range");
  const chatsPrev = $("#chats-prev");
  const chatsNext = $("#chats-next");

  const traceForm = $("#trace-form");
  const traceContent = $("#trace-content");
  const traceEmpty = $("#trace-empty");
  const traceResult = $("#trace-result");
  const traceRequest = $("#trace-request");
  const traceChat = $("#trace-chat");
  const traceCommands = $("#trace-commands");

  // 탭별 상태 (seq: 늦게 도착한 이전 응답이 최신 결과를 덮어쓰지 않도록 요청마다 번호를 붙임)
  const state = {
    loaded: { overview: false, requests: false, chats: false },
    overviewSeq: 0,
    traceSeq: 0,
    requests: { skip: 0, total: 0, seq: 0 },
    chats: { skip: 0, total: 0, seq: 0 },
  };

  // ---------- 로그인 상태 ----------
  const getToken = () => localStorage.getItem(TOKEN_KEY);

  function saveUser(user) {
    if (!user) return;
    localStorage.setItem(USERNAME_KEY, user.username);
    if (user.role) localStorage.setItem(ROLE_KEY, user.role);
    else localStorage.removeItem(ROLE_KEY);
  }

  function clearAuth() {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USERNAME_KEY);
    localStorage.removeItem(ROLE_KEY);
  }

  // ---------- API 통신 ----------
  async function apiRequest(path, { method = "GET", body, auth = true } = {}) {
    const headers = {};
    if (body !== undefined) headers["Content-Type"] = "application/json";
    const token = getToken();
    if (auth && token) headers["Authorization"] = "Bearer " + token;
    const res = await fetch(path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    let data = null;
    try {
      data = await res.json();
    } catch {
      // 본문이 JSON이 아니면 data 없이 처리
    }
    return { res, data };
  }

  const requestIdText = (data) => (data && data.request_id ? `, 요청 ID ${data.request_id}` : "");
  const detailOf = (data, fallback) => (data && typeof data.detail === "string" && data.detail ? data.detail : fallback);

  /**
   * 관리자 API 공통 처리: 401이면 다시 로그인, 403이면 권한 없음 화면, 그 밖의 오류는 상단 안내
   * handled에 넣은 상태 코드는 부르는 쪽이 직접 처리 (예: 요청 추적의 404)
   */
  async function fetchAdmin(path, what, handled = []) {
    let result;
    try {
      result = await apiRequest(path);
    } catch {
      showBanner(`${what} 불러오지 못했습니다. 서버와 연결할 수 없습니다.`);
      return null;
    }
    const { res, data } = result;
    if (handled.includes(res.status)) return result;
    if (res.status === 401) {
      handleSessionExpired();
      return null;
    }
    if (res.status === 403) {
      showDenied(localStorage.getItem(USERNAME_KEY));
      return null;
    }
    if (!res.ok || !data) {
      showBanner(`${what} 불러오지 못했습니다 (HTTP ${res.status}${requestIdText(data)}).`);
      return null;
    }
    return result;
  }

  // ---------- 상단 안내 배너 ----------
  function showBanner(message) {
    errorBannerText.textContent = message;
    errorBanner.hidden = false;
  }

  function hideBanner() {
    errorBanner.hidden = true;
    errorBannerText.textContent = "";
  }

  // ---------- 글자·숫자·시각 표시 ----------
  function el(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined && text !== null) element.textContent = text;
    return element;
  }

  const numberFormat = new Intl.NumberFormat("ko-KR");
  const compactFormat = new Intl.NumberFormat("ko-KR", { notation: "compact", maximumFractionDigits: 1 });
  const formatCount = (value) => (value >= 10000 ? compactFormat.format(value) : numberFormat.format(value));
  const formatMs = (value) => (value === null || value === undefined ? "—" : `${numberFormat.format(value)} ms`);
  const formatPercent = (value) => `${Number(value).toFixed(1)}%`;

  // 서버 시각은 timezone 표시 없는 UTC라 'Z'를 붙여 UTC로 읽음 (app.js와 같은 방식)
  function parseServerDate(value) {
    if (typeof value !== "string" || !value) return null;
    const normalized = value.replace(/(\.\d{3})\d+/, "$1");
    const hasTimezone = /(?:[zZ]|[+-]\d{2}:?\d{2})$/.test(normalized);
    const date = new Date(hasTimezone ? normalized : `${normalized}Z`);
    return Number.isNaN(date.getTime()) ? null : date;
  }

  const kstFormat = new Intl.DateTimeFormat("ko-KR", {
    timeZone: TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  });

  // server.log와 같은 "2026-10-31 18:05:03" 모양으로 표시 (한국 시간)
  function formatKst(value) {
    const date = value instanceof Date ? value : parseServerDate(value);
    if (!date) return "—";
    const parts = Object.fromEntries(kstFormat.formatToParts(date).map((part) => [part.type, part.value]));
    return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}:${parts.second}`;
  }

  function formatDuration(seconds) {
    if (typeof seconds !== "number") return "—";
    const days = Math.floor(seconds / 86400);
    const hours = Math.floor((seconds % 86400) / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    if (days) return `${days}일 ${hours}시간`;
    if (hours) return `${hours}시간 ${minutes}분`;
    if (minutes) return `${minutes}분`;
    return `${seconds}초`;
  }

  // 상태 코드 배지: 아이콘(CSS) + 숫자로 표시하고, 스크린리더에는 뜻을 함께 읽어 줌
  function statusTone(code) {
    if (code >= 500) return ["error", "서버 오류"];
    if (code >= 400) return ["warn", "요청 오류"];
    if (code >= 200 && code < 300) return ["ok", "성공"];
    return ["neutral", "기타"];
  }

  function statusBadge(code) {
    const [tone, meaning] = statusTone(code);
    const badge = el("span", "status-badge", String(code));
    badge.dataset.tone = tone;
    badge.setAttribute("aria-label", `상태 코드 ${code} (${meaning})`);
    return badge;
  }

  function toneBadge(tone, text, className = "status-badge") {
    const badge = el("span", className, text);
    badge.dataset.tone = tone;
    return badge;
  }

  function errorCodeCell(code) {
    const td = el("td");
    if (!code) {
      td.append(el("span", "muted", "—"));
      return td;
    }
    td.append(el("span", "mono", code));
    if (ERROR_CODE_LABELS[code]) td.append(el("span", "code-label", ERROR_CODE_LABELS[code]));
    return td;
  }

  function userText(username, userId) {
    if (username) return username;
    return userId ? `#${userId} (삭제된 사용자)` : "—";
  }

  function requestIdButton(requestId) {
    if (!requestId) return el("span", "muted", "—");
    const button = el("button", "link-btn", requestId);
    button.type = "button";
    button.setAttribute("aria-label", `요청 ${requestId} 추적`);
    button.addEventListener("click", () => openTrace(requestId));
    return button;
  }

  function requestCell(method, path) {
    const td = el("td");
    const line = el("span", "request-line");
    line.title = `${method} ${path}`;
    line.append(el("span", "method", method), el("span", "mono", path));
    td.append(line);
    return td;
  }

  function emptyRow(tbody, columns, text) {
    const tr = el("tr", "empty-row");
    const td = el("td", null, text);
    td.colSpan = columns;
    tr.append(td);
    tbody.replaceChildren(tr);
  }

  function setBusy(element, busy) {
    element.setAttribute("aria-busy", String(busy));
  }

  // ---------- 화면 전환 (확인 중 / 로그인 / 권한 없음 / 관리자 화면) ----------
  function showView(name) {
    bootStatus.hidden = name !== "boot";
    loginView.hidden = name !== "login";
    deniedView.hidden = name !== "denied";
    dashboard.hidden = name !== "dashboard";
    renderHeader();
  }

  function renderHeader() {
    const chatLink = el("a", "btn btn-light", "챗봇 화면");
    chatLink.href = "/";
    adminAuth.replaceChildren(chatLink);
    if (!getToken()) return;
    const user = el("span", "auth-user");
    const avatar = el("span", "avatar");
    avatar.setAttribute("aria-hidden", "true");
    user.append(avatar, el("span", "auth-user-name", `${localStorage.getItem(USERNAME_KEY) || "사용자"}님`));
    const logoutBtn = el("button", "btn btn-light", "로그아웃");
    logoutBtn.type = "button";
    logoutBtn.addEventListener("click", logout);
    adminAuth.append(user, logoutBtn);
  }

  function showLogin(notice) {
    resetDashboard();
    showView("login");
    loginNotice.textContent = notice || "관리자 계정으로 로그인하세요.";
    loginMessage.textContent = "";
    loginForm.elements.username.focus();
  }

  function showDenied(username) {
    resetDashboard();
    showView("denied");
    deniedText.replaceChildren(
      `${username || "이"} 계정은 관리자가 아닙니다. 관리자 권한은 서버(DB 파일)에 접근할 수 있는 운영자가 `,
      el("code", null, `python scripts/create_admin.py ${username || "아이디"}`),
      " 명령으로 지정합니다.",
    );
  }

  function handleSessionExpired() {
    clearAuth();
    showLogin("로그인이 만료되었습니다. 다시 로그인해주세요.");
  }

  // 계정이 바뀌면 이전에 불러온 내용을 지우고 처음부터 다시 불러옴
  function resetDashboard() {
    hideTooltip();
    state.loaded = { overview: false, requests: false, chats: false };
    state.requests.skip = 0;
    state.chats.skip = 0;
    state.overviewSeq += 1;
    state.traceSeq += 1;
    state.requests.seq += 1;
    state.chats.seq += 1;
    [overviewContent, requestsContent, chatsContent, traceContent].forEach((element) => setBusy(element, false));
  }

  // ---------- 로그인 확인 ----------
  async function checkAdmin() {
    if (!getToken()) {
      showLogin();
      return;
    }
    showView("boot");
    bootStatus.textContent = "관리자 정보를 확인하는 중...";
    let result;
    try {
      result = await apiRequest("/api/auth/me");
    } catch {
      bootStatus.textContent = "서버와 연결할 수 없습니다. 잠시 후 새로고침해주세요.";
      return;
    }
    const { res, data } = result;
    if (res.status === 401) {
      handleSessionExpired();
      return;
    }
    if (!res.ok || !data) {
      bootStatus.textContent = `관리자 정보를 확인하지 못했습니다 (HTTP ${res.status}${requestIdText(data)}). 잠시 후 새로고침해주세요.`;
      return;
    }
    saveUser(data);
    if (data.role !== ADMIN_ROLE) {
      showDenied(data.username);
      return;
    }
    showView("dashboard");
    route();
  }

  async function handleLogin(event) {
    event.preventDefault();
    const submitBtn = loginForm.querySelector("button[type=submit]");
    const username = loginForm.elements.username.value.trim();
    const password = loginForm.elements.password.value;
    submitBtn.disabled = true;
    loginMessage.textContent = "";
    loginMessage.className = "form-message";
    try {
      const { res, data } = await apiRequest("/api/auth/login", {
        method: "POST",
        body: { username, password },
        auth: false,
      });
      if (!res.ok || !data || !data.access_token) {
        let message = detailOf(data, "로그인하지 못했습니다. 잠시 후 다시 시도해주세요.");
        if (res.status >= 500) message = `서버 오류로 로그인하지 못했습니다 (HTTP ${res.status}${requestIdText(data)}).`;
        loginMessage.textContent = message;
        loginMessage.className = "form-message error";
        return;
      }
      localStorage.setItem(TOKEN_KEY, data.access_token);
      saveUser(data.user || { username });
      loginForm.reset();
      hideBanner();
      await checkAdmin();
    } catch {
      loginMessage.textContent = "서버와 연결할 수 없습니다. 잠시 후 다시 시도해주세요.";
      loginMessage.className = "form-message error";
    } finally {
      submitBtn.disabled = false;
    }
  }

  function logout() {
    apiRequest("/api/auth/logout", { method: "POST" }).catch(() => {});
    clearAuth();
    hideBanner();
    showLogin("로그아웃했습니다. 관리자 계정으로 다시 로그인하세요.");
  }

  // ---------- 탭 ----------
  const TAB_NAMES = ["overview", "requests", "chats", "trace"];

  function selectTab(name, { focus = false, updateHash = true } = {}) {
    const current = tabs.find((tab) => tab.getAttribute("aria-selected") === "true");
    if (!current || current.dataset.tab !== name) adminMain.scrollTop = 0; // 다른 탭으로 가면 맨 위부터
    tabs.forEach((tab) => {
      const selected = tab.dataset.tab === name;
      tab.setAttribute("aria-selected", String(selected));
      tab.tabIndex = selected ? 0 : -1;
      if (selected && focus) tab.focus();
    });
    panels.forEach((panel) => {
      panel.hidden = panel.id !== `panel-${name}`;
    });
    hideTooltip();
    if (updateHash) history.replaceState(null, "", `#${name}`);
    if (name === "overview" && !state.loaded.overview) loadOverview();
    if (name === "requests" && !state.loaded.requests) loadRequests();
    if (name === "chats" && !state.loaded.chats) loadChats();
    // 마우스로 연 요청 추적 탭은 바로 입력할 수 있게 함 (방향키로 탭을 옮길 때는 초점을 탭에 둠)
    if (name === "trace" && traceResult.hidden && !focus) traceForm.elements.request_id.focus();
  }

  // 주소의 # 뒤를 보고 탭을 고름 (#requests, #chats, #trace=요청ID) → 링크로 특정 화면을 공유할 수 있음
  function route() {
    const hash = decodeURIComponent(location.hash.slice(1));
    if (hash.startsWith("trace=")) {
      openTrace(hash.slice("trace=".length));
      return;
    }
    selectTab(TAB_NAMES.includes(hash) ? hash : "overview", { updateHash: false });
  }

  // 방향키로 탭 이동 (WAI-ARIA 탭 패턴)
  function onTabKeydown(event) {
    const index = tabs.indexOf(event.currentTarget);
    let next = null;
    if (event.key === "ArrowRight") next = (index + 1) % tabs.length;
    if (event.key === "ArrowLeft") next = (index - 1 + tabs.length) % tabs.length;
    if (event.key === "Home") next = 0;
    if (event.key === "End") next = tabs.length - 1;
    if (next === null) return;
    event.preventDefault();
    selectTab(tabs[next].dataset.tab, { focus: true });
  }

  // ---------- 1. 서비스 상태 ----------
  async function fetchHealth() {
    try {
      // 헬스체크는 공개 주소라 토큰 없이 요청 (장애면 503과 같은 형식의 본문이 옴)
      const { res, data } = await apiRequest("/health", { auth: false });
      return { status: res.status, data };
    } catch {
      return null;
    }
  }

  async function loadOverview() {
    const seq = ++state.overviewSeq;
    setBusy(overviewContent, true);
    const [health, summary] = await Promise.all([
      fetchHealth(),
      fetchAdmin("/api/admin/summary", "서비스 상태 요약을"),
    ]);
    if (seq !== state.overviewSeq) return;
    setBusy(overviewContent, false);
    renderHealth(health);
    if (!summary) return;
    state.loaded.overview = true;
    renderSummary(summary.data);
    overviewUpdated.textContent = `마지막 확인: ${formatKst(new Date())} (한국 시간) · 새로고침을 눌러야 다시 불러옵니다.`;
  }

  function fact(label, value, sub) {
    const item = el("div");
    const dd = el("dd");
    if (value instanceof Node) dd.append(value);
    else dd.textContent = value;
    if (sub) dd.append(el("span", "fact-sub", sub));
    item.append(el("dt", null, label), dd);
    return item;
  }

  function renderHealth(health) {
    healthFacts.replaceChildren();
    if (!health || !health.data) {
      healthStatus.replaceChildren(toneBadge("error", "확인 실패", "status-pill"));
      healthFacts.append(fact("헬스체크", "서버에서 응답이 없습니다", "서버가 꺼져 있거나 네트워크 문제일 수 있습니다."));
      return;
    }
    const data = health.data;
    const healthy = data.status === "healthy";
    healthStatus.replaceChildren(
      toneBadge(healthy ? "ok" : "error", healthy ? "정상" : `장애 (HTTP ${health.status})`, "status-pill"),
    );
    const database = data.database || {};
    const ai = data.ai || {};
    healthFacts.append(
      fact("DB 연결", toneBadge(database.status === "ok" ? "ok" : "error", database.status === "ok" ? "정상" : "오류"), database.file || ""),
      fact("AI 설정", toneBadge(ai.configured ? "ok" : "warn", ai.configured ? "설정됨" : "미설정"), ai.configured ? "AI 키가 있습니다" : "AI 키가 없어 대화가 503으로 실패합니다"),
      fact("가동 시간", formatDuration(data.uptime_seconds), "서버를 시작한 뒤 지난 시간"),
      fact("버전", data.version || "—"),
      fact("확인 시각", formatKst(data.checked_at), "GET /health"),
    );
  }

  function kpiTile({ label, value, unit, sub, badge }) {
    const tile = el("div", "kpi");
    const valueLine = el("p", "kpi-value", value);
    if (unit && value !== "—") valueLine.append(el("span", "kpi-unit", unit));
    tile.append(el("p", "kpi-label", label), valueLine);
    if (sub) tile.append(el("p", "kpi-sub", sub));
    if (badge) tile.append(badge);
    return tile;
  }

  function renderSummary(summary) {
    const { users, chats, requests } = summary;
    const errorRequests = requests.status_4xx + requests.status_5xx;
    kpiGrid.replaceChildren(
      kpiTile({
        label: "최근 24시간 요청",
        value: formatCount(requests.total),
        unit: "건",
        sub: `2xx ${formatCount(requests.status_2xx)} · 4xx ${formatCount(requests.status_4xx)} · 5xx ${formatCount(requests.status_5xx)}`,
      }),
      kpiTile({
        label: "서버 오류율 (5xx)",
        value: requests.total ? Number(requests.server_error_rate).toFixed(1) : "—",
        unit: "%",
        sub: `최근 24시간 5xx ${formatCount(requests.status_5xx)}건 / 전체 ${formatCount(requests.total)}건`,
        badge: requests.status_5xx
          ? toneBadge("error", `서버 오류 ${formatCount(requests.status_5xx)}건`)
          : toneBadge("ok", "서버 오류 없음"),
      }),
      kpiTile({
        label: "평균 응답 시간",
        value: requests.avg_duration_ms === null ? "—" : numberFormat.format(requests.avg_duration_ms),
        unit: "ms",
        sub: requests.p95_duration_ms === null ? "최근 24시간 요청 없음" : `p95 ${formatMs(requests.p95_duration_ms)} · 요청 95%가 이 시간 안에 끝남`,
      }),
      kpiTile({
        label: "대화 (전체 기간)",
        value: formatCount(chats.total),
        unit: "건",
        sub: `실패 ${formatCount(chats.failed)}건 · 실패율 ${formatPercent(chats.failure_rate)}`,
        badge: chats.failed_24h
          ? toneBadge("warn", `최근 24시간 실패 ${formatCount(chats.failed_24h)}건`)
          : toneBadge("ok", "최근 24시간 실패 없음"),
      }),
      kpiTile({
        label: "AI 평균 응답 시간",
        value: chats.avg_latency_ms_24h === null ? "—" : numberFormat.format(chats.avg_latency_ms_24h),
        unit: "ms",
        sub: "최근 24시간 동안 성공한 대화 기준",
      }),
      kpiTile({
        label: "사용자",
        value: formatCount(users.total),
        unit: "명",
        sub: `관리자 ${formatCount(users.admins)}명 · 최근 24시간 가입 ${formatCount(users.new_24h)}명`,
      }),
    );

    renderBars(failureBars, chats.failures_by_type, {
      total: chats.failed,
      empty: "실패한 대화가 없습니다.",
      label: (code) => FAILURE_TYPE_LABELS[code] || code,
      shareText: "실패한 대화의",
      // 실패 종류를 누르면 대화 로그 탭에서 실패한 대화만 보여줌
      onSelect: () => showFailedChats(),
    });
    renderBars(errorCodeBars, requests.top_error_codes, {
      total: errorRequests,
      empty: "최근 24시간 동안 오류 응답이 없습니다.",
      label: (code) => ERROR_CODE_LABELS[code] || code,
      shareText: "최근 24시간 오류 요청의",
      // 오류 코드를 누르면 요청 로그 탭에서 같은 기간·같은 코드의 요청만 보여줌
      onSelect: (code) => showRequestsWithErrorCode(code),
    });

    if (!summary.recent_errors.length) {
      emptyRow(recentErrorsBody, 7, "오류 응답이 없습니다.");
    } else {
      recentErrorsBody.replaceChildren(...summary.recent_errors.map((log) => {
        const tr = el("tr");
        const user = el("td", "nowrap", userText(log.username, log.user_id));
        const duration = el("td", "num", formatMs(log.duration_ms));
        const statusTd = el("td");
        statusTd.append(statusBadge(log.status_code));
        const idTd = el("td");
        idTd.append(requestIdButton(log.request_id));
        tr.append(el("td", "nowrap", formatKst(log.created_at)), statusTd, requestCell(log.method, log.path), errorCodeCell(log.error_code), user, duration, idTd);
        return tr;
      }));
    }
  }

  // 가로 막대 목록: 많은 순, 막대 하나의 색, 막대 끝에 값 (올리거나 Tab으로 고르면 비율 안내)
  function renderBars(list, items, { total, empty, label, shareText, onSelect }) {
    list.replaceChildren();
    if (!items.length) {
      list.append(el("li", "empty-note", empty));
      return;
    }
    const max = Math.max(...items.map((item) => item.count));
    items.forEach((item) => {
      const share = total ? Math.round((item.count / total) * 100) : 0;
      const name = label(item.code);
      const li = el("li");
      const row = el("button", "bar-row");
      row.type = "button";
      row.setAttribute("aria-label", `${name} (${item.code}) ${item.count}건, ${shareText} ${share}%`);
      const labelBox = el("span", "bar-label");
      labelBox.append(el("span", null, name), el("small", null, item.code));
      const track = el("span", "bar-track");
      const fill = el("span", "bar-fill");
      fill.style.width = `${Math.max((item.count / max) * 100, 1)}%`;
      track.append(fill);
      row.append(labelBox, track, el("span", "bar-value", `${numberFormat.format(item.count)}건`));
      const tip = () => showTooltip(row, `${numberFormat.format(item.count)}건 · ${share}%`, `${name} (${shareText} ${share}%)`);
      row.addEventListener("pointerenter", tip);
      row.addEventListener("focus", tip);
      row.addEventListener("pointerleave", hideTooltip);
      row.addEventListener("blur", hideTooltip);
      row.addEventListener("click", () => onSelect(item.code));
      li.append(row);
      list.append(li);
    });
  }

  function showTooltip(target, valueText, labelText) {
    tooltip.replaceChildren(el("strong", null, valueText), document.createTextNode(labelText));
    tooltip.hidden = false;
    const rect = target.getBoundingClientRect();
    const tip = tooltip.getBoundingClientRect();
    const left = Math.min(Math.max(8, rect.left + rect.width / 2 - tip.width / 2), window.innerWidth - tip.width - 8);
    let top = rect.top - tip.height - 6;
    if (top < 8) top = rect.bottom + 6;
    tooltip.style.left = `${left}px`;
    tooltip.style.top = `${top}px`;
  }

  function hideTooltip() {
    tooltip.hidden = true;
  }

  // ---------- 2. 요청 로그 ----------
  function requestParams() {
    const form = requestsFilter.elements;
    const params = new URLSearchParams({ skip: String(state.requests.skip), limit: String(PAGE_SIZE) });
    if (form.since_hours.value) params.set("since_hours", form.since_hours.value);
    if (form.status.value !== "all") params.set("status", form.status.value);
    const path = form.path.value.trim();
    if (path) params.set("path", path);
    const username = form.username.value.trim();
    if (username) params.set("username", username);
    const errorCode = form.error_code.value.trim().toUpperCase();
    if (errorCode) params.set("error_code", errorCode);
    if (form.min_duration_ms.value !== "") params.set("min_duration_ms", form.min_duration_ms.value);
    if (form.exclude_admin.checked) params.set("exclude_admin", "true");
    return params;
  }

  async function loadRequests() {
    const seq = ++state.requests.seq;
    setBusy(requestsContent, true);
    const result = await fetchAdmin(`/api/admin/requests?${requestParams()}`, "요청 로그를", [422]);
    if (seq !== state.requests.seq) return;
    setBusy(requestsContent, false);
    if (!result) return;
    if (result.res.status === 422) {
      showBanner(`조건을 확인해주세요: ${detailOf(result.data, "입력값이 올바르지 않습니다.")}`);
      return;
    }
    hideBanner();
    state.loaded.requests = true;
    const page = result.data;
    state.requests.total = page.total;
    if (!page.items.length) {
      emptyRow(requestsBody, 8, "조건에 맞는 요청이 없습니다.");
    } else {
      requestsBody.replaceChildren(...page.items.map((log) => {
        const tr = el("tr");
        const statusTd = el("td");
        statusTd.append(statusBadge(log.status_code));
        const idTd = el("td");
        idTd.append(requestIdButton(log.request_id));
        tr.append(
          el("td", "nowrap", formatKst(log.created_at)),
          statusTd,
          requestCell(log.method, log.path),
          el("td", "num", formatMs(log.duration_ms)),
          el("td", "nowrap", userText(log.username, log.user_id)),
          errorCodeCell(log.error_code),
          el("td", "mono nowrap", log.client_ip || "—"),
          idTd,
        );
        return tr;
      }));
    }
    updatePager(requestsRange, requestsPrev, requestsNext, page, "요청");
  }

  function updatePager(rangeEl, prevBtn, nextBtn, page, noun) {
    const shown = page.items.length;
    rangeEl.textContent = page.total && shown
      ? `총 ${numberFormat.format(page.total)}건 중 ${numberFormat.format(page.skip + 1)}–${numberFormat.format(page.skip + shown)}번째 ${noun}`
      : `총 ${numberFormat.format(page.total)}건`;
    prevBtn.disabled = page.skip === 0;
    nextBtn.disabled = page.skip + shown >= page.total;
  }

  // 조건 입력값을 한 번에 정함 (값을 주지 않은 항목은 기본값)
  function setRequestFilters(values = {}) {
    const form = requestsFilter.elements;
    form.since_hours.value = values.since_hours || "";
    form.status.value = values.status || "all";
    form.path.value = values.path || "";
    form.username.value = values.username || "";
    form.error_code.value = values.error_code || "";
    form.min_duration_ms.value = values.min_duration_ms || "";
    form.exclude_admin.checked = values.exclude_admin !== undefined ? values.exclude_admin : true;
  }

  function showRequestsWithErrorCode(code) {
    // 요약 통계는 최근 24시간, 관리자 화면 요청까지 세므로 같은 조건으로 보여줌
    setRequestFilters({ since_hours: "24", error_code: code, exclude_admin: false });
    state.requests.skip = 0;
    const wasLoaded = state.loaded.requests;
    selectTab("requests"); // 처음 여는 탭이면 여기서 불러옴
    if (wasLoaded) loadRequests();
  }

  // ---------- 3. 대화 로그 ----------
  function chatParams() {
    const form = chatsFilter.elements;
    const params = new URLSearchParams({ skip: String(state.chats.skip), limit: String(PAGE_SIZE) });
    if (form.status.value !== "all") params.set("status", form.status.value);
    const username = form.username.value.trim();
    if (username) params.set("username", username);
    return params;
  }

  async function loadChats() {
    const seq = ++state.chats.seq;
    setBusy(chatsContent, true);
    const result = await fetchAdmin(`/api/admin/chat-logs?${chatParams()}`, "대화 로그를", [422]);
    if (seq !== state.chats.seq) return;
    setBusy(chatsContent, false);
    if (!result) return;
    if (result.res.status === 422) {
      showBanner(`조건을 확인해주세요: ${detailOf(result.data, "입력값이 올바르지 않습니다.")}`);
      return;
    }
    hideBanner();
    state.loaded.chats = true;
    const page = result.data;
    state.chats.total = page.total;
    chatsList.replaceChildren();
    if (!page.items.length) {
      chatsList.append(el("li", "empty-note", "조건에 맞는 대화가 없습니다."));
    } else {
      chatsList.append(...page.items.map(chatLogCard));
      updateExpandButtons();
    }
    updatePager(chatsRange, chatsPrev, chatsNext, page, "대화");
  }

  function chatLogCard(log) {
    const failed = log.status === "FAILED";
    const li = el("li", failed ? "chat-log failed" : "chat-log");
    const meta = el("div", "chat-log-meta");
    meta.append(
      el("span", null, formatKst(log.created_at)),
      el("span", "chat-log-user", userText(log.username, log.user_id)),
      toneBadge(failed ? "error" : "ok", failed ? "실패" : "성공"),
    );
    if (failed) {
      const type = log.error_type || "UNKNOWN";
      meta.append(el("span", null, `${FAILURE_TYPE_LABELS[type] || type} (${type})`));
    }
    meta.append(el("span", null, `AI 응답 시간 ${formatMs(log.latency_ms)}`));
    const idWrap = el("span", null, "요청 ID ");
    idWrap.append(requestIdButton(log.request_id));
    meta.append(idWrap);

    const text = el("dl", "chat-log-text");
    text.append(el("dt", null, "질문"), el("dd", null, log.prompt), el("dt", null, "응답"), el("dd", null, log.response));

    const expand = el("button", "expand-btn", "전체 보기");
    expand.type = "button";
    expand.hidden = true;
    expand.setAttribute("aria-expanded", "false");
    expand.addEventListener("click", () => {
      const expanded = li.classList.toggle("expanded");
      expand.textContent = expanded ? "접기" : "전체 보기";
      expand.setAttribute("aria-expanded", String(expanded));
    });
    li.append(meta, text, expand);
    return li;
  }

  // 3줄을 넘어 잘린 질문·응답이 있는 카드에만 '전체 보기' 버튼을 보여줌
  function updateExpandButtons() {
    requestAnimationFrame(() => {
      chatsList.querySelectorAll(".chat-log").forEach((card) => {
        const button = card.querySelector(".expand-btn");
        if (card.classList.contains("expanded")) {
          button.hidden = false;
          return;
        }
        const clipped = [...card.querySelectorAll(".chat-log-text dd")].some((dd) => dd.scrollHeight > dd.clientHeight + 1);
        button.hidden = !clipped;
      });
    });
  }

  function setChatFilters(values = {}) {
    chatsFilter.elements.status.value = values.status || "all";
    chatsFilter.elements.username.value = values.username || "";
  }

  function showFailedChats() {
    setChatFilters({ status: "FAILED" });
    state.chats.skip = 0;
    const wasLoaded = state.loaded.chats;
    selectTab("chats");
    if (wasLoaded) loadChats();
  }

  // ---------- 4. 요청 추적 ----------
  function openTrace(requestId) {
    traceForm.elements.request_id.value = requestId;
    selectTab("trace", { updateHash: false });
    runTrace(requestId);
  }

  async function runTrace(rawId) {
    const requestId = rawId.trim();
    if (!/^[0-9A-Za-z-]{1,16}$/.test(requestId)) {
      showTraceMessage("요청 ID는 영문·숫자·하이픈으로 된 16자 이하 값입니다. (예: 1a2b3c4d)");
      history.replaceState(null, "", "#trace");
      return;
    }
    history.replaceState(null, "", `#trace=${encodeURIComponent(requestId)}`);
    const seq = ++state.traceSeq;
    setBusy(traceContent, true);
    const result = await fetchAdmin(`/api/admin/requests/${encodeURIComponent(requestId)}`, "요청 기록을", [404, 422]);
    if (seq !== state.traceSeq) return;
    setBusy(traceContent, false);
    if (!result) return;
    if (result.res.status === 404) {
      showTraceMessage(`요청 ID ${requestId}의 기록이 없습니다. 요청 로그는 /api/로 시작하는 요청만 저장합니다.`);
      return;
    }
    if (result.res.status === 422) {
      showTraceMessage(detailOf(result.data, "요청 ID 형식이 올바르지 않습니다."));
      return;
    }
    hideBanner();
    renderTrace(result.data);
  }

  function showTraceMessage(text) {
    traceResult.hidden = true;
    traceEmpty.hidden = false;
    traceEmpty.textContent = text;
  }

  function renderTrace(trace) {
    traceEmpty.hidden = true;
    traceResult.hidden = false;

    const request = trace.request;
    if (request) {
      const facts = el("dl", "facts");
      const method = el("span");
      method.append(el("span", "method", request.method), el("span", "mono", request.path));
      facts.append(
        fact("시각 (한국 시간)", formatKst(request.created_at)),
        fact("요청", method),
        fact("상태 코드", statusBadge(request.status_code)),
        fact("응답 시간", formatMs(request.duration_ms), "요청을 받고 응답할 때까지"),
        fact("사용자", userText(request.username, request.user_id)),
        fact("오류 코드", request.error_code || "—", ERROR_CODE_LABELS[request.error_code] || ""),
        fact("IP", request.client_ip || "—"),
        fact("브라우저 (User-Agent)", request.user_agent || "—"),
      );
      traceRequest.replaceChildren(facts);
    } else {
      traceRequest.replaceChildren(el("p", "empty-note", "요청 로그에 기록이 없습니다. (요청 로그 저장에 실패한 경우 대화 로그만 남을 수 있습니다)"));
    }

    const chat = trace.chat_log;
    if (chat) {
      const failed = chat.status === "FAILED";
      const facts = el("dl", "facts");
      const type = chat.error_type || (failed ? "UNKNOWN" : null);
      facts.append(
        fact("시각 (한국 시간)", formatKst(chat.created_at)),
        fact("사용자", userText(chat.username, chat.user_id)),
        fact("결과", toneBadge(failed ? "error" : "ok", failed ? "실패" : "성공")),
        fact("실패 종류", type ? `${FAILURE_TYPE_LABELS[type] || type}` : "—", type || ""),
        fact("AI 응답 시간", formatMs(chat.latency_ms), "AI 호출부터 응답까지"),
      );
      const prompt = el("div", "trace-text");
      prompt.append(el("h4", null, "질문"), el("p", null, chat.prompt));
      const response = el("div", "trace-text");
      response.append(el("h4", null, failed ? "응답 (사용자에게 보낸 안내 문구)" : "응답"), el("p", null, chat.response));
      traceChat.replaceChildren(facts, prompt, response);
    } else {
      traceChat.replaceChildren(el("p", "empty-note", "이 요청에서 저장된 대화가 없습니다. 대화(POST /api/chat) 요청이 아니거나, 대화를 저장하기 전에 끝난 요청입니다."));
    }

    traceCommands.replaceChildren(
      commandLine("Mac / Linux", `grep "\\[${trace.request_id}\\]" server.log`),
      commandLine("Windows PowerShell", `Select-String -Path server.log -Pattern "${trace.request_id}"`),
    );
  }

  function commandLine(label, command) {
    const box = el("div", "command");
    const line = el("div", "command-line");
    const copyBtn = el("button", "btn btn-light", "복사");
    copyBtn.type = "button";
    copyBtn.setAttribute("aria-label", `${label} 명령 복사`);
    copyBtn.addEventListener("click", async () => {
      copyBtn.textContent = (await copyText(command)) ? "복사됨" : "직접 선택해 복사하세요";
      setTimeout(() => {
        copyBtn.textContent = "복사";
      }, 1500);
    });
    line.append(el("code", null, command), copyBtn);
    box.append(el("span", "command-label", label), line);
    return box;
  }

  async function copyText(text) {
    try {
      // https나 localhost에서만 쓸 수 있는 클립보드 API
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // http 주소 등 클립보드 API를 못 쓰는 환경을 위한 예전 방식
      const area = el("textarea");
      area.value = text;
      area.setAttribute("readonly", "");
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.append(area);
      area.select();
      let copied = false;
      try {
        copied = document.execCommand("copy");
      } catch {
        copied = false;
      }
      area.remove();
      return copied;
    }
  }

  // ---------- 이벤트 연결 ----------
  tabs.forEach((tab) => {
    tab.addEventListener("click", () => selectTab(tab.dataset.tab));
    tab.addEventListener("keydown", onTabKeydown);
  });
  $("#overview-refresh").addEventListener("click", loadOverview);
  loginForm.addEventListener("submit", handleLogin);
  $("#switch-account").addEventListener("click", () => {
    apiRequest("/api/auth/logout", { method: "POST" }).catch(() => {});
    clearAuth();
    showLogin("다른 계정으로 로그인하세요.");
  });
  $("#error-banner-close").addEventListener("click", hideBanner);

  requestsFilter.addEventListener("submit", (event) => {
    event.preventDefault();
    state.requests.skip = 0;
    loadRequests();
  });
  $("#requests-reset").addEventListener("click", () => {
    setRequestFilters();
    state.requests.skip = 0;
    loadRequests();
  });
  requestsPrev.addEventListener("click", () => {
    state.requests.skip = Math.max(0, state.requests.skip - PAGE_SIZE);
    loadRequests();
  });
  requestsNext.addEventListener("click", () => {
    state.requests.skip += PAGE_SIZE;
    loadRequests();
  });

  chatsFilter.addEventListener("submit", (event) => {
    event.preventDefault();
    state.chats.skip = 0;
    loadChats();
  });
  $("#chats-reset").addEventListener("click", () => {
    setChatFilters();
    state.chats.skip = 0;
    loadChats();
  });
  chatsPrev.addEventListener("click", () => {
    state.chats.skip = Math.max(0, state.chats.skip - PAGE_SIZE);
    loadChats();
  });
  chatsNext.addEventListener("click", () => {
    state.chats.skip += PAGE_SIZE;
    loadChats();
  });

  traceForm.addEventListener("submit", (event) => {
    event.preventDefault();
    runTrace(traceForm.elements.request_id.value);
  });

  // 주소의 #을 직접 바꿨을 때도 해당 탭으로 이동
  window.addEventListener("hashchange", () => {
    if (!dashboard.hidden) route();
  });
  adminMain.addEventListener("scroll", hideTooltip, { passive: true });
  window.addEventListener("resize", () => {
    hideTooltip();
    if (!chatsList.closest(".panel").hidden) updateExpandButtons();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") hideTooltip();
  });
  // 다른 탭(브라우저 탭)에서 로그아웃하거나 다른 계정으로 로그인하면 이 화면도 맞춰 다시 확인
  window.addEventListener("storage", (event) => {
    if (event.key === TOKEN_KEY) checkAdmin();
  });

  checkAdmin();
})();
