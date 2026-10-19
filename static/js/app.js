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
  const authInfo = $("#auth-info");
  const authModal = $("#auth-modal");
  const loginForm = $("#login-form");
  const registerForm = $("#register-form");
  const loginMessage = $("#login-message");
  const registerMessage = $("#register-message");

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

  // ---------- 헤더 로그인 정보 ----------
  // [안내서 대비 변경] 안내서는 innerHTML에 username을 그대로 넣어 HTML이 섞인 아이디가 실행될 수 있으므로,
  // 요소를 직접 만들어 textContent로 넣고 onclick 대신 이벤트 리스너를 붙임
  function renderAuthInfo() {
    authInfo.replaceChildren();
    if (getToken()) {
      const name = document.createElement("span");
      name.className = "auth-user";
      name.textContent = `👤 ${localStorage.getItem(USERNAME_KEY) || "사용자"}님`;
      authInfo.append(name, createButton("로그아웃", "btn btn-secondary", logout));
    } else {
      authInfo.append(
        createButton("로그인", "btn btn-secondary", () => openAuthModal("login")),
        createButton("회원가입", "btn btn-primary", () => openAuthModal("register")),
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
    chatInput.disabled = !loggedIn;
    sendBtn.disabled = !loggedIn;
    chatInput.placeholder = loggedIn
      ? "AI에게 질문을 입력하세요... (Enter 전송, Shift+Enter 줄바꿈)"
      : "🔒 로그인 후 질문을 입력할 수 있습니다.";
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
      updateAuthState();
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
  }

  // ---------- 말풍선 ----------
  function appendMessage(role, text, status) {
    const bubble = document.createElement("div");
    bubble.className = `message ${role}`;
    setMessageContent(bubble, text, status);
    chatMessages.append(bubble);
    scrollToBottom();
    return bubble;
  }

  function setMessageContent(bubble, text, status = "SUCCESS") {
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
    charCount.textContent = `${length} / ${MAX_PROMPT_LENGTH}`;
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

  // ---------- 질문 전송 ----------
  async function sendChatMessage() {
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

    appendMessage("user", prompt);
    chatInput.value = "";
    onInputChange();
    const reply = appendMessage("assistant", "AI가 답변을 작성하고 있습니다...");

    try {
      // 신재은 get_current_user가 읽는 Authorization: Bearer 헤더를 붙여 전송
      const { res, data } = await apiRequest("/api/chat", { method: "POST", body: { prompt }, auth: true });

      if (res.status === 401) {
        handleSessionExpired(reply);
        return;
      }
      // [안내서 대비 변경] 안내서 코드는 422·500 응답에서도 data.response를 그대로 써 "undefined"가 표시되므로 상태별로 안내
      if (res.status === 422) {
        setMessageContent(reply, getErrorMessage(data, `질문은 1자 이상 ${MAX_PROMPT_LENGTH}자 이하로 입력해주세요.`), "FAILED");
        return;
      }
      if (!res.ok || !data || typeof data.response !== "string") {
        setMessageContent(reply, "서버에서 오류가 발생했습니다. 잠시 후 다시 시도해주세요.", "FAILED");
        return;
      }
      // AI 호출이 실패·타임아웃이어도 서버는 200 + status "FAILED" + 안내 문구를 주므로 같은 화면에 그대로 표시
      setMessageContent(reply, data.response, data.status);
    } catch {
      setMessageContent(reply, "⚠️ 네트워크 통신 오류가 발생했습니다.", "FAILED");
    }
  }

  // 토큰이 만료됐거나 서버가 로그인을 거부한 경우
  function handleSessionExpired(bubble) {
    setMessageContent(bubble, "❌ 세션이 만료되었습니다. 다시 로그인해주세요.", "FAILED");
    clearAuth();
    updateAuthState();
    // [안내서 대비 변경] 안내서 처리(토큰 삭제·입력창 잠금)에 더해 로그인 모달을 바로 열어줌
    openAuthModal("login");
  }

  // ---------- 이벤트 연결 ----------
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
  loginForm.addEventListener("submit", handleLogin);
  registerForm.addEventListener("submit", handleRegister);
  document.querySelectorAll("[data-auth-mode]").forEach((tab) => {
    tab.addEventListener("click", () => setAuthMode(tab.dataset.authMode));
  });
  document.querySelectorAll("[data-open-modal]").forEach((button) => {
    button.addEventListener("click", () => openAuthModal(button.dataset.openModal));
  });
  authModal.querySelector("[data-close-modal]").addEventListener("click", closeAuthModal);

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
})();
