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

let teams = {};
let demo = false;
let currentStatus = "idle";

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

function render(state) {
  currentStatus = state.status;
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
  resetButton.disabled = finished || paused;
  finishButton.disabled = finished || paused;

  farewell.hidden = true;
  hint.hidden = false;

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
    return;
  }

  if (state.status === "finished") {
    stage.className = "finished";
    stage.style.background = "";
    title.textContent = "Konečné pořadí";
    hint.hidden = true;
    farewell.hidden = false;
    statusEl.textContent = "Soutěž skončila";
    return;
  }

  if (state.status === "locked") {
    const team = teams[String(state.team)];
    stage.className = "locked";
    stage.style.background = team.color;
    title.textContent = team.name;
    hint.textContent = "Kolik bodů za odpověď?";
    statusEl.textContent = `${team.name} přihlášen`;
    return;
  }

  stage.className = "idle";
  stage.style.background = "";
  title.textContent = "Čeká se na přihlášení";
  hint.textContent = "První zmáčknuté tlačítko získá slovo";
  statusEl.textContent = "Připraveno";
}

async function reset() {
  if (currentStatus === "finished" || currentStatus === "paused") {
    return;
  }
  await fetch("/api/reset", { method: "POST" });
}

async function awardPoints(points) {
  const response = await fetch("/api/award", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ points }),
  });
  if (!response.ok) {
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
  for (const team of Object.values(teams)) {
    const dot = document.createElement("span");
    dot.style.background = team.color;
    dots.appendChild(dot);
  }

  render(await (await fetch("/api/state")).json());

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
    if (event.key === "1" || event.key === "2" || event.key === "3") {
      const n = Number(event.key);
      if (currentStatus === "locked") {
        event.preventDefault();
        awardPoints(n);
        return;
      }
      if (demo && currentStatus === "idle") {
        demoBuzz(n);
      }
    }
  });
}

start();
