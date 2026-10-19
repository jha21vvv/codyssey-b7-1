/*
 * [권태현 전담] 웹 챗봇 프론트엔드: 로그인 상태 관리와 Fetch API 통신
 * 로그인 응답의 access_token을 localStorage에 저장하고,
 * 인증이 필요한 요청에는 Authorization: Bearer <토큰> 헤더를 붙입니다. (업무분장안내서 규칙 4)
 */
(() => {
  "use strict";

  // [안내서 대비 변경] 안내서 "받아올 것" 항목의 "token" 대신, 안내서 코드와 신재은 안내서에 맞춰 "access_token" 키로 저장
  const TOKEN_KEY = "access_token";
  const USERNAME_KEY = "username";
  const MAX_PROMPT_LENGTH = 1000; // 조명환 ChatRequest·validate_prompt와 같은 최대 길이

  const $ = (selector) => document.querySelector(selector);
  const chatMessages = $("#chat-messages");
  const chatForm = $("#chat-form");
  const chatInput = $("#chat-input");
  const sendBtn = $("#send-btn");
  const charCount = $("#char-count");
  const inputHint = $("#input-hint");
  const loginNotice = $("#login-notice");
  const errorBanner = $("#error-banner");
  const errorBannerText = $("#error-banner-text");
  const welcomeMessage = chatMessages.querySelector(".welcome");
  const historyList = $("#history-list");
  const historyStatus = $("#history-status");
  const historyCount = $("#history-count");
  const sidebarToggle = $("#sidebar-toggle");
  const sidebarBackdrop = $("#sidebar-backdrop");
  const authInfo = $("#auth-info");
  const authModal = $("#auth-modal");
  const loginForm = $("#login-form");
  const registerForm = $("#register-form");
  const loginMessage = $("#login-message");
  const registerMessage = $("#register-message");

  let isSending = false; // AI 응답을 기다리는 중인지 (중복 전송 방지)
  let entrySeq = 0; // 새로 보낸 질문의 사이드바 항목과 말풍선을 잇는 번호

  // ---------- 로그인 상태 저장 ----------
  const getToken = () => localStorage.getItem(TOKEN_KEY);

  function saveAuth(token, username) {
    localStorage.setItem(TOKEN_KEY, token);
    localStorage.setItem(USERNAME_KEY, username);
  }

  function clearAuth() {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USERNAME_KEY);
  }

  // ---------- API 통신 ----------
  async function apiRequest(path, { method = "GET", body, auth = false } = {}) {
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
      // 본문이 JSON이 아닌 응답(빈 본문, 프록시 오류 페이지 등)은 data 없이 처리
    }
    return { res, data };
  }

  // FastAPI 오류 응답에서 사용자에게 보여줄 문구를 꺼냄
  // HTTPException은 detail이 한국어 문자열이고, 입력값 검증(422)은 detail이 영어 배열이라 그때는 fallback 사용
  function getErrorMessage(data, fallback) {
    const detail = data && data.detail;
    return typeof detail === "string" && detail ? detail : fallback;
  }

  // ---------- 상단 에러 안내 배너 ----------
  // 네트워크·서버 오류와 세션 만료처럼 말풍선만으로는 놓치기 쉬운 상황을 화면 위쪽에 알림
  // (다음 질문이 성공하거나 다시 로그인하면 자동으로 닫힘)
  function showBanner(message) {
    errorBannerText.textContent = message;
    errorBanner.hidden = false;
  }

  function hideBanner() {
    errorBanner.hidden = true;
    errorBannerText.textContent = "";
  }

  // ---------- 헤더 로그인 정보 ----------
  // [안내서 대비 변경] 안내서는 innerHTML에 username을 그대로 넣어 HTML이 섞인 아이디가 실행될 수 있으므로,
  // 요소를 직접 만들어 textContent로 넣고 onclick 대신 이벤트 리스너를 붙임
  function renderAuthInfo() {
    authInfo.replaceChildren();
    if (getToken()) {
      const user = document.createElement("span");
      user.className = "auth-user";
      const avatar = document.createElement("span");
      avatar.className = "avatar";
      avatar.setAttribute("aria-hidden", "true");
      const name = document.createElement("span");
      name.className = "auth-user-name";
      name.textContent = `${localStorage.getItem(USERNAME_KEY) || "사용자"}님`;
      user.append(avatar, name);
      authInfo.append(user, createButton("로그아웃", "btn btn-light", logout));
    } else {
      authInfo.append(
        createButton("로그인", "btn btn-light", () => openAuthModal("login")),
        createButton("회원가입", "btn btn-bright", () => openAuthModal("register")),
      );
    }
  }

  function createButton(label, className, onClick) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = className;
    button.textContent = label;
    button.addEventListener("click", onClick);
    return button;
  }

  function updateAuthState() {
    const loggedIn = Boolean(getToken());
    renderAuthInfo();
    // 비로그인 상태에서는 입력창과 전송 버튼을 잠금 (백엔드 401 차단과 함께 2중 방어, 업무분장안내서 규칙 3)
    // 응답을 기다리는 동안에는 다음 질문을 미리 쓸 수 있게 입력창은 두고 전송 버튼만 잠금
    chatInput.disabled = !loggedIn;
    sendBtn.disabled = !loggedIn || isSending;
    // [안내서 대비 변경] 안내서 문구("🔒 로그인 후 질문을 입력할 수 있습니다.")는 휴대폰 화면에서 잘리므로 짧게 줄임
    // (자세한 안내는 입력창 위 로그인 안내 줄이 담당, 단축키 안내는 입력창 아래 .keyboard-hint로 옮김)
    chatInput.placeholder = loggedIn
      ? "질문을 입력하세요..."
      : "🔒 로그인이 필요합니다";
    // [안내서 대비 변경] 안내서의 잠금·placeholder 처리에 더해, 입력창 위에 로그인/회원가입 버튼이 있는 안내 줄을 보여줌
    loginNotice.hidden = loggedIn;
  }

  // ---------- 로그인 / 회원가입 모달 ----------
  function openAuthModal(mode) {
    if (!authModal.open) authModal.showModal();
    setAuthMode(mode);
  }

  function closeAuthModal() {
    authModal.close();
  }

  function setAuthMode(mode) {
    const isLogin = mode === "login";
    loginForm.hidden = !isLogin;
    registerForm.hidden = isLogin;
    document.querySelectorAll("[data-auth-mode]").forEach((tab) => {
      tab.setAttribute("aria-selected", String(tab.dataset.authMode === mode));
    });
    setFormMessage(loginMessage, "");
    setFormMessage(registerMessage, "");
    (isLogin ? loginForm : registerForm).elements.username.focus();
  }

  function setFormMessage(element, text, type = "error") {
    element.textContent = text;
    element.className = `form-message ${type}`;
  }

  async function handleLogin(event) {
    event.preventDefault();
    const submitBtn = loginForm.querySelector("button[type=submit]");
    const username = loginForm.elements.username.value.trim();
    const password = loginForm.elements.password.value;

    submitBtn.disabled = true;
    setFormMessage(loginMessage, "");
    try {
      const { res, data } = await apiRequest("/api/auth/login", {
        method: "POST",
        body: { username, password },
      });
      if (!res.ok || !data || !data.access_token) {
        setFormMessage(loginMessage, getErrorMessage(data, "아이디 또는 비밀번호를 확인해주세요."));
        return;
      }
      saveAuth(data.access_token, (data.user && data.user.username) || username);
      loginForm.reset();
      closeAuthModal();
      hideBanner();
      updateAuthState();
      // 다른 계정의 대화가 남지 않도록 대화창을 비우고, 이 사용자의 지난 대화를 서버에서 다시 불러옴
      resetConversation();
      loadHistory();
    } catch {
      setFormMessage(loginMessage, "서버와 연결할 수 없습니다. 잠시 후 다시 시도해주세요.");
    } finally {
      submitBtn.disabled = false;
    }
  }

  async function handleRegister(event) {
    event.preventDefault();
    const submitBtn = registerForm.querySelector("button[type=submit]");
    const username = registerForm.elements.username.value.trim();
    const password = registerForm.elements.password.value;

    if (password !== registerForm.elements.passwordConfirm.value) {
      setFormMessage(registerMessage, "비밀번호 확인이 일치하지 않습니다.");
      return;
    }

    submitBtn.disabled = true;
    setFormMessage(registerMessage, "");
    try {
      const { res, data } = await apiRequest("/api/auth/register", {
        method: "POST",
        body: { username, password },
      });
      if (!res.ok) {
        const fallback = res.status === 422
          ? "아이디는 3~50자, 비밀번호는 4~100자로 입력해주세요."
          : "회원가입에 실패했습니다. 잠시 후 다시 시도해주세요.";
        setFormMessage(registerMessage, getErrorMessage(data, fallback));
        return;
      }
      registerForm.reset();
      setAuthMode("login");
      loginForm.elements.username.value = username;
      loginForm.elements.password.focus();
      setFormMessage(loginMessage, "회원가입이 완료되었습니다. 로그인해주세요.", "success");
    } catch {
      setFormMessage(registerMessage, "서버와 연결할 수 없습니다. 잠시 후 다시 시도해주세요.");
    } finally {
      submitBtn.disabled = false;
    }
  }

  function logout() {
    // 요청 헤더가 만들어진 뒤에 토큰을 지우므로, 서버 응답을 기다리지 않고 바로 화면을 로그아웃 상태로 바꿈
    apiRequest("/api/auth/logout", { method: "POST", auth: true }).catch(() => {});
    clearAuth();
    updateAuthState();
    resetConversation();
    closeSidebar();
  }

  // ---------- 말풍선 ----------
  // entryKey: 사이드바 항목을 눌렀을 때 찾아갈 질문 말풍선 표시
  function createBubble(role, text, status, entryKey) {
    const bubble = document.createElement("div");
    bubble.className = `message ${role}`;
    if (entryKey) bubble.dataset.entry = entryKey;
    setMessageContent(bubble, text, status);
    return bubble;
  }

  function appendMessage(role, text, status, entryKey) {
    const bubble = createBubble(role, text, status, entryKey);
    chatMessages.append(bubble);
    scrollToBottom();
    return bubble;
  }

  // 로그아웃·재로그인 시 이전 사용자의 대화가 화면에 남지 않도록 첫 인사만 남기고 비움
  function resetConversation() {
    chatMessages.querySelectorAll(":scope > :not(.welcome)").forEach((element) => element.remove());
    historyList.replaceChildren();
    updateHistoryStatus();
  }

  // [안내서 대비 변경] 안내서의 "⏳ ...작성하고 있습니다" 문구 대신 점 3개 애니메이션을 보여주고, 같은 문구는 스크린리더용으로 남김
  function appendLoadingMessage() {
    const bubble = document.createElement("div");
    bubble.className = "message assistant loading";
    bubble.setAttribute("aria-busy", "true");
    const dots = document.createElement("span");
    dots.className = "typing";
    dots.setAttribute("aria-hidden", "true");
    dots.append(document.createElement("span"), document.createElement("span"), document.createElement("span"));
    const label = document.createElement("span");
    label.className = "visually-hidden";
    label.textContent = "AI가 답변을 작성하고 있습니다";
    bubble.append(dots, label);
    chatMessages.append(bubble);
    scrollToBottom();
    return bubble;
  }

  function setMessageContent(bubble, text, status = "SUCCESS") {
    bubble.classList.remove("loading");
    bubble.removeAttribute("aria-busy");
    // 질문과 AI 응답은 항상 textContent로 넣어 HTML로 해석되지 않게 함 (XSS 방지)
    bubble.textContent = text;
    // [안내서 대비 변경] 안내서는 실패 시 글자색만 직접 바꾸지만, .failed 클래스로 말풍선 전체를 실패 스타일로 바꿈
    bubble.classList.toggle("failed", status === "FAILED");
  }

  function scrollToBottom() {
    chatMessages.scrollTop = chatMessages.scrollHeight;
  }

  // ---------- 질문 입력 ----------
  function showInputHint(text) {
    inputHint.textContent = text;
    inputHint.hidden = false;
  }

  function hideInputHint() {
    inputHint.hidden = true;
    inputHint.textContent = "";
  }

  function onInputChange() {
    // 서버(validate_prompt)처럼 앞뒤 공백을 뺀 길이로 셈
    const length = chatInput.value.trim().length;
    charCount.textContent = `${length.toLocaleString("ko-KR")} / ${MAX_PROMPT_LENGTH.toLocaleString("ko-KR")}`;
    charCount.classList.toggle("over", length > MAX_PROMPT_LENGTH);
    if (!inputHint.hidden && length > 0 && length <= MAX_PROMPT_LENGTH) hideInputHint();
    autoResize();
  }

  // 입력 내용에 맞춰 입력창 높이를 늘림 (CSS max-height까지)
  function autoResize() {
    const border = chatInput.offsetHeight - chatInput.clientHeight;
    chatInput.style.height = "auto";
    chatInput.style.height = `${chatInput.scrollHeight + border}px`;
  }

  // 추천 질문: 바로 보내지 않고 입력창에 채워 고칠 수 있게 함 (비로그인이면 로그인 창을 엶)
  function useSuggestion(text) {
    if (!getToken()) {
      openAuthModal("login");
      return;
    }
    chatInput.value = text;
    onInputChange();
    chatInput.focus();
  }

  // ---------- 질문 전송 ----------
  function setSending(value) {
    isSending = value;
    chatForm.setAttribute("aria-busy", String(value));
    updateAuthState();
  }

  async function sendChatMessage() {
    if (isSending) return;
    if (!getToken()) {
      openAuthModal("login");
      return;
    }
    const prompt = chatInput.value.trim();
    // [안내서 대비 변경] 안내서의 alert 대신 입력창 아래에 안내하고, 최대 길이도 서버에 보내기 전에 막음
    if (!prompt) {
      showInputHint("질문을 입력해주세요.");
      return;
    }
    if (prompt.length > MAX_PROMPT_LENGTH) {
      showInputHint(`질문은 최대 ${MAX_PROMPT_LENGTH}자까지 입력할 수 있습니다.`);
      return;
    }
    hideInputHint();

    const entryKey = `new-${++entrySeq}`;
    const sentToken = getToken();
    appendMessage("user", prompt, "SUCCESS", entryKey);
    chatInput.value = "";
    onInputChange();
    const reply = appendLoadingMessage();
    setSending(true);

    try {
      // 신재은 get_current_user가 읽는 Authorization: Bearer 헤더를 붙여 전송
      const { res, data } = await apiRequest("/api/chat", { method: "POST", body: { prompt }, auth: true });
      // 응답을 기다리는 사이 로그아웃했거나 다른 계정으로 바뀌었으면 결과를 화면에 반영하지 않음
      if (getToken() !== sentToken) return;

      if (res.status === 401) {
        handleSessionExpired(reply);
        // 다시 로그인하면 대화창을 서버 기록으로 새로 그리므로, 보내지 못한 질문은 입력창에 돌려둠
        chatInput.value = prompt;
        onInputChange();
        return;
      }
      // [안내서 대비 변경] 안내서 코드는 422·500 응답에서도 data.response를 그대로 써 "undefined"가 표시되므로 상태별로 안내
      if (res.status === 422) {
        setMessageContent(reply, getErrorMessage(data, `질문은 1자 이상 ${MAX_PROMPT_LENGTH}자 이하로 입력해주세요.`), "FAILED");
        return;
      }
      if (!res.ok || !data || typeof data.response !== "string") {
        setMessageContent(reply, "서버에서 오류가 발생했습니다. 잠시 후 다시 시도해주세요.", "FAILED");
        showBanner(`서버 오류가 발생했습니다 (HTTP ${res.status}). 잠시 후 다시 시도해주세요.`);
        return;
      }
      // AI 호출이 실패·타임아웃이어도 서버는 200 + status "FAILED" + 안내 문구를 주므로 같은 화면에 그대로 표시
      setMessageContent(reply, data.response, data.status);
      hideBanner();
      // 서버는 FAILED 응답도 대화 로그로 저장하므로 사이드바에도 바로 추가
      historyList.prepend(createHistoryItem(entryKey, prompt, data.status, new Date()));
      updateHistoryStatus();
    } catch {
      setMessageContent(reply, "⚠️ 네트워크 통신 오류가 발생했습니다.", "FAILED");
      showBanner("서버와 연결할 수 없습니다. 네트워크 상태를 확인한 뒤 다시 시도해주세요.");
    } finally {
      setSending(false);
    }
  }

  // 토큰이 만료됐거나 서버가 로그인을 거부한 경우 (지난 대화 조회에서는 말풍선 없이 호출)
  function handleSessionExpired(bubble) {
    if (bubble) setMessageContent(bubble, "❌ 세션이 만료되었습니다. 다시 로그인해주세요.", "FAILED");
    clearAuth();
    updateAuthState();
    // [안내서 대비 변경] 안내서 처리(토큰 삭제·입력창 잠금)에 더해 상단 배너로 알리고 로그인 모달을 바로 열어줌
    showBanner("로그인이 만료되었습니다. 다시 로그인해주세요.");
    openAuthModal("login");
  }

  // ---------- 지난 대화 (GET /api/logs/me) ----------
  // 서버 created_at은 timezone 표시가 없는 UTC 시각이라 그대로 읽으면 브라우저가 한국 시각으로 오해함 → 'Z'를 붙여 UTC로 해석
  function parseServerDate(value) {
    if (typeof value !== "string" || !value) return null;
    // 마이크로초(6자리)는 일부 브라우저가 읽지 못하므로 밀리초(3자리)까지만 사용
    const normalized = value.replace(/(\.\d{3})\d+/, "$1");
    const hasTimezone = /(?:[zZ]|[+-]\d{2}:?\d{2})$/.test(normalized);
    const date = new Date(hasTimezone ? normalized : `${normalized}Z`);
    return Number.isNaN(date.getTime()) ? null : date;
  }

  function formatTime(date) {
    if (!date) return "";
    return date.toLocaleString("ko-KR", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
  }

  function setHistoryStatus(text) {
    historyStatus.textContent = text;
    historyStatus.hidden = !text;
  }

  function updateHistoryStatus() {
    const count = historyList.children.length;
    // 제목 옆에 지난 대화 수를 "총 N건"으로 표시
    historyCount.textContent = count ? `총 ${count.toLocaleString("ko-KR")}건` : "";
    historyCount.hidden = !count;
    if (count) setHistoryStatus("");
    else setHistoryStatus(getToken() ? "아직 나눈 대화가 없습니다." : "로그인하면 지난 대화가 여기에 표시됩니다.");
  }

  function createHistoryItem(entryKey, prompt, status, date) {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "history-item";
    button.dataset.entry = entryKey;

    const title = document.createElement("span");
    title.className = "history-item-title";
    title.textContent = prompt;
    const meta = document.createElement("span");
    meta.className = "history-item-meta";
    const time = document.createElement("span");
    time.textContent = formatTime(date);
    meta.append(time);
    if (status === "FAILED") {
      const badge = document.createElement("span");
      badge.className = "badge-failed";
      badge.textContent = "응답 실패";
      meta.append(badge);
    }

    button.append(title, meta);
    button.addEventListener("click", () => focusEntry(entryKey));
    item.append(button);
    return item;
  }

  // 사이드바 항목을 누르면 대화창에서 그 질문으로 이동해 잠깐 강조
  function focusEntry(entryKey) {
    const bubble = chatMessages.querySelector(`.message[data-entry="${CSS.escape(entryKey)}"]`);
    if (!bubble) return;
    bubble.scrollIntoView({ block: "center", behavior: "smooth" });
    bubble.classList.remove("highlight");
    void bubble.offsetWidth; // 같은 항목을 다시 눌러도 강조 애니메이션이 다시 시작되도록 reflow
    bubble.classList.add("highlight");
    clearTimeout(bubble.highlightTimer);
    bubble.highlightTimer = setTimeout(() => bubble.classList.remove("highlight"), 1600);
    closeSidebar();
  }

  function renderHistory(logs) {
    // id가 클수록 최근 대화: 사이드바는 최신순, 대화창은 오래된 순(대화 흐름 순서)으로 보여줌
    const newestFirst = [...logs].sort((a, b) => b.id - a.id);
    const fragment = document.createDocumentFragment();
    [...newestFirst].reverse().forEach((log) => {
      const entryKey = `log-${log.id}`;
      fragment.append(
        createBubble("user", log.prompt, "SUCCESS", entryKey),
        createBubble("assistant", log.response, log.status),
      );
    });
    if (newestFirst.length) {
      const divider = document.createElement("div");
      divider.className = "history-divider";
      divider.setAttribute("role", "separator");
      divider.textContent = "여기까지 지난 대화입니다";
      fragment.append(divider);
    }
    // 불러오는 사이 새로 보낸 질문이 있어도 그 위(첫 인사 바로 아래)에 지난 대화를 넣음
    welcomeMessage.after(fragment);

    const items = newestFirst.map((log) => createHistoryItem(`log-${log.id}`, log.prompt, log.status, parseServerDate(log.created_at)));
    historyList.append(...items);
    updateHistoryStatus();
    scrollToBottom();
  }

  async function loadHistory() {
    const requestToken = getToken();
    if (!requestToken) return;
    setHistoryStatus("지난 대화를 불러오는 중...");
    try {
      const { res, data } = await apiRequest("/api/logs/me", { auth: true });
      // 불러오는 사이 로그아웃했거나 다른 계정으로 바뀌었으면 결과를 버림
      if (getToken() !== requestToken) return;
      if (res.status === 401) {
        handleSessionExpired();
        return;
      }
      if (!res.ok || !Array.isArray(data)) {
        setHistoryStatus("지난 대화를 불러오지 못했습니다.");
        return;
      }
      renderHistory(data);
    } catch {
      if (getToken() === requestToken) setHistoryStatus("지난 대화를 불러오지 못했습니다.");
    }
  }

  // ---------- 모바일 사이드바 ----------
  function openSidebar() {
    document.body.classList.add("sidebar-open");
    sidebarBackdrop.hidden = false;
    sidebarToggle.setAttribute("aria-expanded", "true");
  }

  function closeSidebar() {
    document.body.classList.remove("sidebar-open");
    sidebarBackdrop.hidden = true;
    sidebarToggle.setAttribute("aria-expanded", "false");
  }

  // ---------- 이벤트 연결 ----------
  sidebarToggle.addEventListener("click", () => {
    if (document.body.classList.contains("sidebar-open")) closeSidebar();
    else openSidebar();
  });
  sidebarBackdrop.addEventListener("click", closeSidebar);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && document.body.classList.contains("sidebar-open")) closeSidebar();
  });
  chatForm.addEventListener("submit", (event) => {
    event.preventDefault();
    sendChatMessage();
  });
  chatInput.addEventListener("keydown", (event) => {
    // 한글 조합 중에 누른 Enter는 글자를 확정하는 입력이라 전송하지 않음 (마지막 글자 중복 전송 방지)
    if (event.isComposing || event.keyCode === 229) return;
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      sendChatMessage();
    }
  });
  chatInput.addEventListener("input", onInputChange);
  document.querySelectorAll(".suggestion-chip").forEach((chip) => {
    chip.addEventListener("click", () => useSuggestion(chip.textContent.trim()));
  });
  loginForm.addEventListener("submit", handleLogin);
  registerForm.addEventListener("submit", handleRegister);
  document.querySelectorAll("[data-auth-mode]").forEach((tab) => {
    tab.addEventListener("click", () => setAuthMode(tab.dataset.authMode));
  });
  document.querySelectorAll("[data-open-modal]").forEach((button) => {
    button.addEventListener("click", () => openAuthModal(button.dataset.openModal));
  });
  authModal.querySelector("[data-close-modal]").addEventListener("click", closeAuthModal);
  $("#error-banner-close").addEventListener("click", hideBanner);

  // 모달 바깥(배경)을 눌렀다 뗐을 때만 닫음 (입력창에서 드래그하다 바깥에서 놓는 경우는 제외)
  let pointerDownOnBackdrop = false;
  authModal.addEventListener("pointerdown", (event) => {
    pointerDownOnBackdrop = event.target === authModal;
  });
  authModal.addEventListener("click", (event) => {
    if (pointerDownOnBackdrop && event.target === authModal) closeAuthModal();
  });
  // 닫을 때 입력했던 비밀번호는 남기지 않음
  authModal.addEventListener("close", () => {
    authModal.querySelectorAll("input[type=password]").forEach((input) => {
      input.value = "";
    });
  });

  updateAuthState();
  updateHistoryStatus();
  loadHistory();
})();
