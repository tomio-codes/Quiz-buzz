const stage = document.getElementById("stage");
const title = document.getElementById("title");
const hint = document.getElementById("hint");
const statusEl = document.getElementById("status");
const scoreboard = document.getElementById("scoreboard");
const award = document.getElementById("award");
const dots = document.getElementById("dots");
const resetButton = document.getElementById("reset");
const finishButton = document.getElementById("finish");
const newGameButton = document.getElementById("new-game");
const farewell = document.getElementById("farewell");
const stageScale = document.getElementById("stage-scale");
const stageContent = document.getElementById("stage-content");

let teams = {};
let demo = false;
let currentStatus = "idle";
let lastState = null;
let holdLockedTeamId = null;
let holdLockedTimer = null;
const AWARD_UI_HOLD_MS = 580;

function playBuzz() {
  const ctx = new AudioContext();
  const osc = ctx.createOscillator();
  const gain = ctx.createGain();
  osc.type = "square";
  osc.frequency.value = 740;
  gain.gain.setValueAtTime(0.08, ctx.currentTime);
  gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.28);
  osc.connect(gain);
  gain.connect(ctx.destination);
  osc.start();
  osc.stop(ctx.currentTime + 0.3);
}

function displayTeams(state) {
  const list = Object.keys(teams)
    .sort((a, b) => Number(a) - Number(b))
    .map((id) => ({
      id,
      name: teams[id].name,
      color: teams[id].color,
      score: state.scores[id],
    }));
  if (state.status !== "finished") {
    return list;
  }
  return list.sort((a, b) => b.score - a.score || Number(a.id) - Number(b.id));
}

function renderScoreboard(state) {
  const finished = state.status === "finished";
  scoreboard.replaceChildren();
  displayTeams(state).forEach((team, index) => {
    const row = document.createElement("li");
    row.style.setProperty("--team", team.color);
    const card = document.createElement("div");
    card.className = "team-card";
    const name = document.createElement("span");
    name.className = "team-name";
    name.textContent = team.name;
    const points = document.createElement("span");
    points.className = "team-score";
    points.textContent = String(team.score);
    card.append(name, points);
    if (finished) {
      const place = document.createElement("span");
      place.className = "place";
      const medal = document.createElement("i");
      medal.className = "place-medal fa-solid fa-medal";
      place.append(medal, `${index + 1}. místo`);
      row.append(place, card);
    } else {
      row.append(card);
    }
    scoreboard.append(row);
  });
}

function offlineTeamNames(state) {
  return (state.offline_teams || []).map((id) => teams[String(id)].name);
}

function fitStage() {
  if (stageContent === null || stageScale === null) {
    return;
  }
  stageContent.style.transform = "none";
  stageContent.style.width = "";
  stageScale.style.width = "";
  stageScale.style.height = "";

  const footer = document.querySelector("footer");
  const fit = document.getElementById("stage-fit");
  const fitStyles = fit ? getComputedStyle(fit) : null;
  const padX = fitStyles
    ? parseFloat(fitStyles.paddingLeft) + parseFloat(fitStyles.paddingRight)
    : 0;
  const padY = fitStyles
    ? parseFloat(fitStyles.paddingTop) + parseFloat(fitStyles.paddingBottom)
    : 0;
  const availH = window.innerHeight - footer.offsetHeight - padY;
  const availW = window.innerWidth - padX;
  const isWide = availW / availH >= 1.2;

  const naturalW = stageContent.offsetWidth;
  const naturalH = stageContent.scrollHeight;
  const scaleH = (availH * 0.98) / naturalH;
  const scaleW = (availW * 0.98) / naturalW;

  if (isWide && scaleH < 1) {
    const scale = Math.min(1, scaleH);
    const targetW = availW * 0.98;
    stageContent.style.width = `${targetW / scale}px`;
    stageContent.style.transformOrigin = "top left";
    stageContent.style.transform = `scale(${scale})`;
    stageScale.style.width = `${targetW}px`;
    stageScale.style.height = `${naturalH * scale}px`;
    return;
  }

  const scale = Math.min(1, scaleH, scaleW);
  if (scale >= 0.999) {
    return;
  }

  stageContent.style.width = `${naturalW}px`;
  stageContent.style.transformOrigin = "top left";
  stageContent.style.transform = `scale(${scale})`;
  stageScale.style.width = `${naturalW * scale}px`;
  stageScale.style.height = `${naturalH * scale}px`;
}

function scheduleFitStage() {
  if (holdLockedTeamId !== null) {
    return;
  }
  requestAnimationFrame(fitStage);
}

function clearLockedUiHold() {
  holdLockedTeamId = null;
  if (holdLockedTimer !== null) {
    clearTimeout(holdLockedTimer);
    holdLockedTimer = null;
  }
}

function scheduleLockedUiHold(teamId) {
  clearLockedUiHold();
  holdLockedTeamId = teamId;
  holdLockedTimer = setTimeout(() => {
    holdLockedTeamId = null;
    holdLockedTimer = null;
    if (lastState !== null) {
      render(lastState);
    }
  }, AWARD_UI_HOLD_MS);
}

function lockedUiTeam(state) {
  if (state.status === "locked" && state.team !== null) {
    return state.team;
  }
  if (holdLockedTeamId !== null && state.status === "idle") {
    return holdLockedTeamId;
  }
  return null;
}

function playAwardPop(button) {
  button.classList.remove("award-pop-active");
  void button.offsetWidth;
  button.classList.add("award-pop-active");
  button.addEventListener(
    "animationend",
    () => button.classList.remove("award-pop-active"),
    { once: true },
  );
}

function renderTeamDots(state) {
  const connected = new Set((state.connected_teams || []).map(String));
  for (const dot of dots.querySelectorAll("[data-team-id]")) {
    dot.classList.toggle("offline", !connected.has(dot.dataset.teamId));
  }
}

function render(state) {
  lastState = state;
  if (state.status === "locked") {
    clearLockedUiHold();
  } else if (state.status !== "idle") {
    clearLockedUiHold();
  }

  const lockedTeamId = lockedUiTeam(state);
  currentStatus = state.status;
  renderTeamDots(state);
  renderScoreboard(state);
  const canAward = state.status === "locked";
  for (const button of award.querySelectorAll("button")) {
    button.disabled = !canAward;
  }
  const finished = state.status === "finished";
  const paused = state.status === "paused";
  resetButton.hidden = finished;
  finishButton.hidden = finished;
  newGameButton.hidden = !finished;
  const waiting = state.status === "waiting";
  resetButton.disabled = finished || waiting;
  finishButton.disabled = finished || paused || waiting;

  farewell.hidden = true;
  hint.hidden = false;

  if (state.status === "waiting") {
    stage.className = "waiting";
    stage.style.background = "";
    title.textContent = "Čeká se na tlačítka";
    const names = Object.values(teams)
      .map((team) => team.name)
      .join(", ");
    hint.textContent = `Připojte tlačítka: ${names} (${state.online_count}/${state.min_teams})`;
    statusEl.textContent = "Čekání…";
    scheduleFitStage();
    return;
  }

  if (state.status === "paused") {
    const names = offlineTeamNames(state);
    stage.className = "paused";
    stage.style.background = "";
    if (names.length === 1) {
      title.textContent = `${names[0]} - tlačítko nekomunikuje`;
    } else {
      title.textContent = `${names.join(", ")} nekomunikují`;
    }
    hint.textContent = "Hra je pozastavena do obnovení spojení";
    statusEl.textContent = "Pozastaveno";
    scheduleFitStage();
    return;
  }

  if (state.status === "finished") {
    stage.className = "finished";
    stage.style.background = "";
    title.textContent = "Konečné pořadí";
    hint.hidden = true;
    farewell.hidden = false;
    statusEl.textContent = "Soutěž skončila";
    scheduleFitStage();
    return;
  }

  if (lockedTeamId !== null) {
    const team = teams[String(lockedTeamId)];
    stage.className = "locked";
    stage.style.background = team.color;
    title.textContent = team.name;
    hint.textContent = "Kolik bodů za odpověď?";
    statusEl.textContent =
      state.status === "locked" ? `${team.name} přihlášen` : "Připraveno";
    scheduleFitStage();
    return;
  }

  stage.className = "idle";
  stage.style.background = "";
  title.textContent = "Znáte odpověď? Stiskněte tlačítko!";
  hint.textContent = "První zmáčknuté tlačítko získá slovo";
  statusEl.textContent = "Připraveno";
  scheduleFitStage();
}

async function reset() {
  if (currentStatus === "finished" || currentStatus === "waiting") {
    return;
  }
  await fetch("/api/reset", { method: "POST" });
}

async function awardPoints(points) {
  if (currentStatus !== "locked" || lastState?.team === null || lastState?.team === undefined) {
    return;
  }
  const button = award.querySelector(`button[data-points="${points}"]`);
  if (button === null) {
    return;
  }
  scheduleLockedUiHold(lastState.team);
  playAwardPop(button);
  const response = await fetch("/api/award", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ points }),
  });
  if (!response.ok) {
    clearLockedUiHold();
    if (lastState !== null) {
      render(lastState);
    }
    return;
  }
}

async function finishGame() {
  await fetch("/api/finish", { method: "POST" });
}

async function startNewGame() {
  await fetch("/api/new-game", { method: "POST" });
}

async function demoBuzz(team) {
  await fetch("/api/demo-buzz", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ team }),
  });
}

async function start() {
  const config = await (await fetch("/api/config")).json();
  demo = config.demo;
  teams = await (await fetch("/api/teams")).json();
  dots.innerHTML = "";
  for (const id of Object.keys(teams).sort((a, b) => Number(a) - Number(b))) {
    const dot = document.createElement("span");
    dot.dataset.teamId = id;
    dot.style.setProperty("--team-color", teams[id].color);
    dot.classList.add("offline");
    dots.appendChild(dot);
  }

  render(await (await fetch("/api/state")).json());
  window.addEventListener("resize", scheduleFitStage);
  window.addEventListener("load", scheduleFitStage);

  const events = new EventSource("/api/events");
  events.onmessage = (event) => {
    const next = JSON.parse(event.data);
    if (next.status === "locked" && currentStatus !== "locked") {
      playBuzz();
    }
    render(next);
  };
  events.onerror = () => {
    statusEl.textContent = "Ztráta spojení se serverem";
  };

  award.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-points]");
    if (button === null) {
      return;
    }
    awardPoints(Number(button.dataset.points));
  });
  resetButton.addEventListener("click", reset);
  finishButton.addEventListener("click", finishGame);
  newGameButton.addEventListener("click", startNewGame);
  window.addEventListener("keydown", (event) => {
    if (event.code === "Space" || event.key === "r" || event.key === "R") {
      event.preventDefault();
      reset();
    }
    if (/^[1-4]$/.test(event.key)) {
      const n = Number(event.key);
      if (currentStatus === "locked") {
        event.preventDefault();
        awardPoints(n);
        return;
      }
      if (demo && currentStatus === "idle" && n in teams) {
        event.preventDefault();
        demoBuzz(n);
      }
    }
  });
}

start();
