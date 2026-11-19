(() => {
  const game = window.MiniGolf;
  const hud = document.getElementById("hud");
  const canvas = document.getElementById("game");
  if (!game || !hud || !canvas) return;

  const { speedScale, replay } = document.currentScript.dataset;
  const scale = Number(speedScale);
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = replay === "1" ? "Replay shot" : "Fallback shot";
  button.disabled = true;
  const label = document.createElement("span");
  label.id = "golfbot-status";
  label.setAttribute("role", "status");
  label.textContent = "Connecting to the Pi…";
  hud.append(button, label);

  const readout = document.getElementById("shot-readout");
  const speedValue = document.getElementById("shot-speed");
  const angleValue = document.getElementById("shot-angle");
  const sourceValue = document.getElementById("shot-source");
  if (readout) readout.hidden = false;

  const shotHelp = document.getElementById("shot-button-help");
  if (shotHelp) {
    const name = document.createElement("strong");
    name.textContent = button.textContent;
    shotHelp.append(name, replay === "1" ? " Play the next saved putt." : " Play a putt if the sensors miss your roll.");
    shotHelp.hidden = false;
  } else {
    const keys = document.createElement("small");
    keys.textContent = "←/→ Turn · ↑ Align shot · ↓ Turn around";
    hud.append(keys);
  }

  function showShot(speed = "—", angle = "—", source = "—") {
    if (!readout) return;
    speedValue.textContent = speed;
    angleValue.textContent = angle;
    sourceValue.textContent = source;
  }

  const marker = document.createElement("div");
  marker.id = "golfbot-facing";
  marker.hidden = true;
  marker.setAttribute("aria-hidden", "true");
  Object.assign(marker.style, {
    position: "absolute", width: "0", height: "0",
    pointerEvents: "none",
  });
  const arrow = document.createElement("span");
  arrow.textContent = "➜";
  Object.assign(arrow.style, {
    position: "absolute", left: "14px", top: "0",
    transform: "translateY(-50%)", font: "bold 31px/1 system-ui",
    color: "#fff", textShadow: "0 1px 3px #000, 0 0 4px #000",
  });
  marker.append(arrow);
  canvas.parentElement.append(marker);

  let manualFacing = null;
  const heldAimKeys = new Set();
  let fadeTimer;

  function facingAngle() {
    return manualFacing ?? game.idealShot().angle;
  }

  function drawFacing() {
    if (marker.hidden) return;
    const { x, y } = game.state;
    marker.style.left = `${canvas.offsetLeft + x * canvas.clientWidth / game.CONFIG.BOARD_W}px`;
    marker.style.top = `${canvas.offsetTop + y * canvas.clientHeight / game.CONFIG.BOARD_H}px`;
    marker.style.transform = `rotate(${-facingAngle()}deg)`;
  }

  function stopAiming() {
    clearTimeout(fadeTimer);
    heldAimKeys.clear();
    marker.hidden = true;
  }

  marker.addEventListener("transitionend", event => {
    if (event.propertyName === "opacity" && marker.style.opacity === "0") {
      marker.hidden = true;
    }
  });

  window.addEventListener("keydown", event => {
    const { key, altKey, ctrlKey, metaKey } = event;
    if (altKey || ctrlKey || metaKey ||
        !["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(key) ||
        game.state.moving || game.state.sunk) return;
    event.preventDefault();
    heldAimKeys.add(key);
    clearTimeout(fadeTimer);
    marker.style.transition = "none";
    marker.style.opacity = "1";
    marker.hidden = false;
    if (key === "ArrowUp") {
      manualFacing = null;
    } else if (key !== "ArrowDown" || !event.repeat) {
      const turn = key === "ArrowLeft" ? 5 : key === "ArrowRight" ? -5 : 180;
      manualFacing = (facingAngle() + turn + 360) % 360;
    }
    drawFacing();
  });

  window.addEventListener("keyup", event => {
    if (heldAimKeys.delete(event.key) && heldAimKeys.size === 0) {
      fadeTimer = setTimeout(() => {
        marker.style.transition = "opacity 200ms ease-out";
        marker.style.opacity = "0";
      }, 500);
    }
  });
  window.addEventListener("blur", stopAiming);
  window.addEventListener("resize", drawFacing);
  new ResizeObserver(drawFacing).observe(canvas.parentElement);
  drawFacing();

  const events = new EventSource("/events");
  let inputStatus = { ready: false, text: label.textContent };
  let requesting = false;
  let requestTimer;

  function finishRequest() {
    clearTimeout(requestTimer);
    requesting = false;
  }

  function updateButton() {
    button.disabled = requesting || !inputStatus.ready || game.state.moving || game.state.sunk;
  }

  for (const event of ["shot", "stop", "sunk"]) {
    game.on(event, () => {
      if (event === "shot") {
        stopAiming();
        showShot("—", "—", "Mouse putt");
      }
      updateButton();
      drawFacing();
    });
  }
  game.on("reset", () => {
    stopAiming();
    manualFacing = null;
    showShot();
    label.textContent = inputStatus.text;
    updateButton();
  });
  events.addEventListener("status", event => {
    inputStatus = JSON.parse(event.data);
    finishRequest();
    label.textContent = inputStatus.text;
    updateButton();
  });
  events.addEventListener("error", () => {
    inputStatus = { ready: false, text: "Shot connection lost. Reconnecting…" };
    finishRequest();
    label.textContent = inputStatus.text;
    updateButton();
  });
  events.addEventListener("shot", event => {
    const shot = JSON.parse(event.data);
    finishRequest();
    if (shot.event === "shot_unresolved") {
      label.textContent = "Aim unavailable. Use Fallback shot to play in the shown direction.";
      updateButton();
      return;
    }
    if (shot.event !== "golf_shot" || !Number.isFinite(shot.speed_mps) ||
        shot.speed_mps <= 0 || !Number.isFinite(shot.aim_deg) ||
        Math.abs(shot.aim_deg) >= 90) {
      updateButton();
      return;
    }
    const angle = facingAngle() - shot.aim_deg;
    if (!game.shoot(shot.speed_mps * scale, angle)) {
      label.textContent = game.state.sunk ? "Reset to play again." : "Wait for the ball to stop.";
      updateButton();
      return;
    }
    const source = { beam: "Pico", camera: "camera estimate", default: "fallback" }[shot.speed_source] || "shot input";
    const speed = `${(shot.speed_mps / 0.44704).toFixed(2)} mph`;
    const degrees = Math.abs(shot.aim_deg).toFixed(2);
    const direction = degrees === "0.00" ? "straight" : shot.aim_deg < 0 ? "left" : "right";
    const angleReadout = `${degrees}° ${direction}`;
    showShot(speed, angleReadout, source);
    label.textContent = readout ? inputStatus.text : `${speed} · ${angleReadout} · ${source}`;
    updateButton();
  });

  button.addEventListener("click", async () => {
    requesting = true;
    updateButton();
    requestTimer = setTimeout(() => {
      finishRequest();
      updateButton();
    }, 1500);
    try {
      const response = await fetch("/shot", { method: "POST" });
      if (!response.ok) {
        finishRequest();
        updateButton();
      }
    } catch {
      finishRequest();
      label.textContent = "Could not send shot request.";
      updateButton();
    }
  });
})();
