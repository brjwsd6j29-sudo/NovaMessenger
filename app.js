(() => {
  "use strict";

  // ===================== ЭЛЕМЕНТЫ =====================
  const loginScreen = document.getElementById("loginScreen");
  const appScreen = document.getElementById("app");
  const loginForm = document.getElementById("loginForm");
  const pincodeInput = document.getElementById("pincodeInput");
  const loginError = document.getElementById("loginError");

  const profileChip = document.getElementById("profileChip");
  const profileDropdown = document.getElementById("profileDropdown");
  const balanceValue = document.getElementById("balanceValue");
  const nicknameValue = document.getElementById("nicknameValue");
  const pdBalance = document.getElementById("pdBalance");
  const pdBank = document.getElementById("pdBank");
  const pdLvl = document.getElementById("pdLvl");
  const logoutBtn = document.getElementById("logoutBtn");

  const menuView = document.getElementById("menuView");
  const crashView = document.getElementById("crashView");
  const openCrashBtn = document.getElementById("openCrashBtn");
  const backToMenuBtn = document.getElementById("backToMenuBtn");

  const historyStrip = document.getElementById("historyStrip");
  const phaseLabel = document.getElementById("phaseLabel");
  const multiplierValue = document.getElementById("multiplierValue");
  const countdownValue = document.getElementById("countdownValue");
  const rocketCanvas = document.getElementById("rocketCanvas");
  const rctx = rocketCanvas.getContext("2d");

  const betAmountInput = document.getElementById("betAmountInput");
  const autoCashoutToggle = document.getElementById("autoCashoutToggle");
  const autoCashoutInput = document.getElementById("autoCashoutInput");
  const actionBtn = document.getElementById("actionBtn");
  const betError = document.getElementById("betError");

  const winToast = document.getElementById("winToast");
  const winMult = document.getElementById("winMult");
  const winAmount = document.getElementById("winAmount");
  const confettiCanvas = document.getElementById("confettiCanvas");
  const cctx = confettiCanvas.getContext("2d");

  // ===================== СОСТОЯНИЕ =====================
  let profile = null;
  let ws = null;
  let currentState = null;
  let myBetPlaced = false;      // ставка сделана в текущем раунде
  let myBetActive = false;      // ставка ещё не забрана
  let lastSeenRoundId = null;
  let curvePoints = [];

  function fmt(n) {
    return Math.round(n).toLocaleString("ru-RU").replace(/,/g, " ");
  }

  // ===================== ЛОГИН =====================
  pincodeInput.addEventListener("input", () => {
    pincodeInput.value = pincodeInput.value.replace(/\D/g, "").slice(0, 6);
  });

  loginForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    loginError.hidden = true;
    const pincode = pincodeInput.value.trim();
    if (pincode.length !== 6) {
      loginError.textContent = "Введите 6-значный пинкод из бота";
      loginError.hidden = false;
      return;
    }
    try {
      const res = await fetch("/api/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pincode }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || "Неверный пинкод");
      }
      await bootApp();
    } catch (err) {
      loginError.textContent = err.message;
      loginError.hidden = false;
    }
  });

  logoutBtn.addEventListener("click", async () => {
    await fetch("/api/logout", { method: "POST" });
    if (ws) ws.close();
    location.reload();
  });

  profileChip.addEventListener("click", () => {
    profileDropdown.hidden = !profileDropdown.hidden;
  });
  document.addEventListener("click", (e) => {
    if (!profileChip.contains(e.target) && !profileDropdown.contains(e.target)) {
      profileDropdown.hidden = true;
    }
  });

  // ===================== ЗАГРУЗКА ПРОФИЛЯ =====================
  async function fetchProfile() {
    const res = await fetch("/api/profile");
    if (!res.ok) throw new Error("unauth");
    profile = await res.json();
    renderProfile();
  }

  function renderProfile(animateBalance = false) {
    if (!profile) return;
    nicknameValue.textContent = profile.nickname;
    pdBank.textContent = fmt(profile.bank);
    pdLvl.textContent = profile.lvl;
    if (animateBalance) {
      balanceValue.parentElement.classList.remove("balance-pulse");
      void balanceValue.parentElement.offsetWidth; // restart animation
      balanceValue.parentElement.classList.add("balance-pulse");
    }
    balanceValue.textContent = fmt(profile.balance);
    pdBalance.textContent = fmt(profile.balance);
  }

  async function bootApp() {
    try {
      await fetchProfile();
    } catch {
      loginScreen.hidden = false;
      appScreen.hidden = true;
      return;
    }
    loginScreen.hidden = true;
    appScreen.hidden = false;
    connectWS();
  }

  // ===================== НАВИГАЦИЯ =====================
  openCrashBtn.addEventListener("click", () => {
    menuView.hidden = true;
    crashView.hidden = false;
    resizeCanvas();
  });
  backToMenuBtn.addEventListener("click", () => {
    crashView.hidden = true;
    menuView.hidden = false;
  });

  // ===================== СТАВКА: БЫСТРЫЕ КНОПКИ =====================
  document.querySelectorAll(".qbtn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const cur = parseInt(betAmountInput.value || "0", 10);
      const bal = profile ? profile.balance : 0;
      if (btn.dataset.op === "half") betAmountInput.value = Math.max(100, Math.floor(cur / 2));
      if (btn.dataset.op === "double") betAmountInput.value = Math.min(bal, cur * 2 || 100);
      if (btn.dataset.op === "max") betAmountInput.value = bal;
    });
  });

  autoCashoutToggle.addEventListener("change", () => {
    autoCashoutInput.disabled = !autoCashoutToggle.checked;
  });

  // ===================== WEBSOCKET =====================
  function connectWS() {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    ws = new WebSocket(`${proto}//${location.host}/ws/crash`);
    ws.onmessage = (evt) => {
      const state = JSON.parse(evt.data);
      handleState(state);
    };
    ws.onclose = () => {
      setTimeout(() => { if (!appScreen.hidden) connectWS(); }, 1500);
    };
  }

  function handleState(state) {
    const prevPhase = currentState ? currentState.phase : null;
    currentState = state;

    if (state.round_id !== lastSeenRoundId) {
      lastSeenRoundId = state.round_id;
      myBetPlaced = false;
      myBetActive = false;
      curvePoints = [];
      betError.hidden = true;
    }

    renderHistory(state.history);
    renderPhase(state, prevPhase);
    drawRocket(state);
  }

  function renderHistory(history) {
    historyStrip.innerHTML = "";
    history.forEach((val) => {
      const chip = document.createElement("div");
      let cls = "hc-low";
      if (val >= 10) cls = "hc-high";
      else if (val >= 2) cls = "hc-mid";
      chip.className = `history-chip ${cls}`;
      chip.textContent = `${val.toFixed(2)}x`;
      historyStrip.appendChild(chip);
    });
  }

  function renderPhase(state, prevPhase) {
    multiplierValue.classList.remove("mv-running", "mv-crashed");

    if (state.phase === "waiting") {
      phaseLabel.textContent = "Ставки принимаются";
      multiplierValue.textContent = "1.00x";
      countdownValue.textContent = Math.max(0, Math.ceil(state.phase_ends_in));
      updateActionButton("waiting");
    } else if (state.phase === "running") {
      phaseLabel.textContent = "Полёт";
      multiplierValue.classList.add("mv-running");
      multiplierValue.textContent = `${state.multiplier.toFixed(2)}x`;
      countdownValue.textContent = "";
      updateActionButton("running", state.multiplier);
    } else if (state.phase === "crashed") {
      phaseLabel.textContent = "Крах!";
      multiplierValue.classList.add("mv-crashed");
      multiplierValue.textContent = `${state.crash_point.toFixed(2)}x`;
      countdownValue.textContent = "";
      updateActionButton("crashed");

      if (prevPhase === "running" && myBetActive) {
        myBetActive = false;
        showBetLostFeedback(state.crash_point);
      }
    }
  }

  function showBetLostFeedback(crashPoint) {
    betError.hidden = false;
    betError.textContent = `Крах на ${crashPoint.toFixed(2)}x — ставка сгорела`;
    fetchProfile();
  }

  function updateActionButton(phase, multiplier) {
    actionBtn.classList.remove("state-cashout", "state-locked");

    if (phase === "waiting") {
      if (myBetPlaced) {
        actionBtn.textContent = "Ставка принята ✓";
        actionBtn.classList.add("state-locked");
        actionBtn.disabled = true;
      } else {
        actionBtn.textContent = "Поставить";
        actionBtn.disabled = false;
      }
    } else if (phase === "running") {
      if (myBetActive) {
        const bet = parseInt(betAmountInput.value || "0", 10);
        const potential = Math.floor(bet * multiplier);
        actionBtn.textContent = `Забрать ${fmt(potential)}`;
        actionBtn.classList.add("state-cashout");
        actionBtn.disabled = false;
      } else {
        actionBtn.textContent = myBetPlaced ? "Уже забрано" : "Раунд уже идёт";
        actionBtn.classList.add("state-locked");
        actionBtn.disabled = true;
      }
    } else {
      actionBtn.textContent = "Дождитесь раунда";
      actionBtn.classList.add("state-locked");
      actionBtn.disabled = true;
    }
  }

  actionBtn.addEventListener("click", async () => {
    if (!currentState) return;
    betError.hidden = true;

    if (currentState.phase === "waiting" && !myBetPlaced) {
      const amount = parseInt(betAmountInput.value || "0", 10);
      const body = { amount };
      if (autoCashoutToggle.checked) {
        body.auto_cashout = parseFloat(autoCashoutInput.value || "0");
      }
      try {
        const res = await fetch("/api/crash/bet", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Ошибка ставки");
        profile.balance = data.balance;
        renderProfile();
        myBetPlaced = true;
        myBetActive = true;
        updateActionButton("waiting");
      } catch (err) {
        betError.textContent = err.message;
        betError.hidden = false;
      }
    } else if (currentState.phase === "running" && myBetActive) {
      try {
        const res = await fetch("/api/crash/cashout", { method: "POST" });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Ошибка забора");
        myBetActive = false;
        profile.balance = data.balance;
        renderProfile(true);
        updateActionButton("running", currentState.multiplier);
        showWinToast(data.multiplier, data.win);
        launchConfetti();
      } catch (err) {
        betError.textContent = err.message;
        betError.hidden = false;
      }
    }
  });

  // ===================== ТОСТ ВЫИГРЫША =====================
  let toastTimer = null;
  function showWinToast(mult, amount) {
    winMult.textContent = `${mult.toFixed(2)}x`;
    winAmount.textContent = fmt(amount);
    winToast.hidden = false;
    requestAnimationFrame(() => winToast.classList.add("show"));
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
      winToast.classList.remove("show");
      setTimeout(() => { winToast.hidden = true; }, 250);
    }, 2600);
  }

  // ===================== КОНФЕТТИ =====================
  let confettiParticles = [];
  let confettiRAF = null;
  function resizeConfetti() {
    confettiCanvas.width = window.innerWidth;
    confettiCanvas.height = window.innerHeight;
  }
  window.addEventListener("resize", resizeConfetti);
  resizeConfetti();

  function launchConfetti() {
    const colors = ["#F5C94B", "#7C5CFF", "#38E1C6", "#FF9DB2"];
    for (let i = 0; i < 60; i++) {
      confettiParticles.push({
        x: confettiCanvas.width / 2 + (Math.random() - 0.5) * 120,
        y: 90,
        vx: (Math.random() - 0.5) * 6,
        vy: Math.random() * -6 - 2,
        size: Math.random() * 5 + 3,
        color: colors[Math.floor(Math.random() * colors.length)],
        life: 0,
      });
    }
    if (!confettiRAF) confettiRAF = requestAnimationFrame(tickConfetti);
  }

  function tickConfetti() {
    cctx.clearRect(0, 0, confettiCanvas.width, confettiCanvas.height);
    confettiParticles.forEach((p) => {
      p.vy += 0.18;
      p.x += p.vx;
      p.y += p.vy;
      p.life += 1;
      cctx.globalAlpha = Math.max(0, 1 - p.life / 90);
      cctx.fillStyle = p.color;
      cctx.fillRect(p.x, p.y, p.size, p.size);
    });
    confettiParticles = confettiParticles.filter((p) => p.life < 90);
    cctx.globalAlpha = 1;
    if (confettiParticles.length > 0) {
      confettiRAF = requestAnimationFrame(tickConfetti);
    } else {
      confettiRAF = null;
    }
  }

  // ===================== АНИМАЦИЯ РАКЕТЫ =====================
  function resizeCanvas() {
    const rect = rocketCanvas.parentElement.getBoundingClientRect();
    rocketCanvas.width = rect.width * devicePixelRatio;
    rocketCanvas.height = rect.height * devicePixelRatio;
    rocketCanvas.style.width = rect.width + "px";
    rocketCanvas.style.height = rect.height + "px";
    rctx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
  }
  window.addEventListener("resize", () => { if (!crashView.hidden) resizeCanvas(); });

  function drawRocket(state) {
    const w = rocketCanvas.clientWidth;
    const h = rocketCanvas.clientHeight;
    rctx.clearRect(0, 0, w, h);

    if (state.phase === "waiting") {
      curvePoints = [];
      return;
    }

    const mult = state.phase === "crashed" ? state.crash_point : state.multiplier;
    curvePoints.push(mult);
    if (curvePoints.length > 400) curvePoints.shift();

    const maxMult = Math.max(2, mult * 1.15);
    const padding = 24;
    const toXY = (i, m) => {
      const x = padding + (i / Math.max(1, curvePoints.length - 1)) * (w - padding * 2) * 0.85;
      const y = h - padding - (Math.min(m, maxMult) / maxMult) * (h - padding * 2);
      return [x, y];
    };

    // трасса
    rctx.beginPath();
    curvePoints.forEach((m, i) => {
      const [x, y] = toXY(i, m);
      if (i === 0) rctx.moveTo(x, y);
      else rctx.lineTo(x, y);
    });
    const grad = rctx.createLinearGradient(0, 0, w, 0);
    grad.addColorStop(0, "#38E1C6");
    grad.addColorStop(1, state.phase === "crashed" ? "#FF4D6D" : "#7C5CFF");
    rctx.strokeStyle = grad;
    rctx.lineWidth = 3;
    rctx.lineJoin = "round";
    rctx.stroke();

    // заливка под трассой
    if (curvePoints.length > 1) {
      const [lastX] = toXY(curvePoints.length - 1, curvePoints[curvePoints.length - 1]);
      rctx.lineTo(lastX, h - padding);
      rctx.lineTo(padding, h - padding);
      rctx.closePath();
      rctx.fillStyle = "rgba(124,92,255,0.08)";
      rctx.fill();
    }

    // ракета/точка на конце
    if (curvePoints.length > 0) {
      const [x, y] = toXY(curvePoints.length - 1, curvePoints[curvePoints.length - 1]);
      rctx.beginPath();
      rctx.arc(x, y, 6, 0, Math.PI * 2);
      rctx.fillStyle = state.phase === "crashed" ? "#FF4D6D" : "#F5C94B";
      rctx.shadowColor = state.phase === "crashed" ? "#FF4D6D" : "#F5C94B";
      rctx.shadowBlur = 16;
      rctx.fill();
      rctx.shadowBlur = 0;

      if (state.phase === "running") {
        rctx.font = "20px sans-serif";
        rctx.textAlign = "center";
        rctx.textBaseline = "middle";
        rctx.save();
        rctx.translate(x, y - 14);
        rctx.rotate(-0.5);
        rctx.fillText("🚀", 0, 0);
        rctx.restore();
      }
    }
  }

  // ===================== СТАРТ =====================
  bootApp();
})();
