const frame = document.getElementById("pet-frame");
const pet = document.getElementById("pet");
const paw = document.getElementById("paw");
const countEl = document.getElementById("count");
const countBox = document.getElementById("pat-count");
const plus = document.getElementById("plus");

let base = 0;
let pending = 0;
let sending = false;

localStorage.removeItem("million-pats-count");
localStorage.removeItem("million-pats-photo");

let armed = false;
let active = false;

function format(n) {
  return n.toLocaleString("en-US");
}

function shown() {
  return base + pending;
}

function render() {
  countEl.textContent = format(shown());
}

async function pull() {
  if (pending > 0 || sending) return;
  try {
    const response = await fetch("/api/pats", { cache: "no-store" });
    if (!response.ok) return;
    const data = await response.json();
    if (pending > 0 || sending) return;
    base = Number(data.count) || 0;
    render();
  } catch (err) {
    // Keep the last number on screen if the server is briefly unreachable.
  }
}

async function flush() {
  if (sending || pending === 0) return;
  sending = true;
  const batch = Math.min(pending, 30);
  let saved = false;
  try {
    const response = await fetch("/api/pats", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ count: batch }),
    });
    if (response.ok) {
      const data = await response.json();
      pending -= batch;
      base = Number(data.count) || 0;
      render();
      saved = true;
    }
  } catch (err) {
    // Leave the pats in pending and try again.
  } finally {
    sending = false;
  }
  if (pending > 0) {
    if (saved) flush();
    else setTimeout(flush, 1500);
  }
}

function pointInFrame(clientX, clientY) {
  const rect = frame.getBoundingClientRect();
  return {
    x: clientX - rect.left,
    y: clientY - rect.top,
    width: rect.width,
    height: rect.height,
    inside:
      clientX >= rect.left &&
      clientX <= rect.right &&
      clientY >= rect.top &&
      clientY <= rect.bottom,
  };
}

function petAt(x, y, width, height) {
  const progress = Math.min(1, Math.max(0, x / width));
  const wobble = Math.sin(x / 16) * 5;
  const lean = (progress - 0.5) * 10;
  const squash = 1 - Math.sin(progress * Math.PI) * 0.035;

  pet.style.transform =
    `translate(${lean}px, ${wobble}px) rotate(${lean / 6}deg) scale(1, ${squash})`;

  paw.hidden = false;
  paw.style.left = `${x}px`;
  paw.style.top = `${Math.min(height - 36, Math.max(24, y))}px`;
  paw.style.transform = `rotate(${Math.sin(x / 22) * 8}deg)`;

  if (progress < 0.32) armed = true;
  if (armed && progress > 0.74) {
    armed = false;
    registerPat(x, y);
  }
}

function registerPat(x, y) {
  pending += 1;
  render();
  flush();
  countBox.classList.remove("pop");
  void countBox.offsetWidth;
  countBox.classList.add("pop");

  plus.style.left = `${x}px`;
  plus.classList.remove("show");
  void plus.offsetWidth;
  plus.classList.add("show");

  pet.animate(
    [
      { transform: pet.style.transform },
      { transform: "translate(0, 6px) scale(1.04, 0.94)" },
      { transform: "translate(0, -2px) scale(1, 1)" },
    ],
    { duration: 280, easing: "ease-out" }
  );
}

function onPointer(clientX, clientY) {
  const point = pointInFrame(clientX, clientY);
  if (!point.inside) {
    resetPose();
    return;
  }
  active = true;
  petAt(point.x, point.y, point.width, point.height);
}

function resetPose() {
  active = false;
  paw.hidden = true;
  pet.style.transform = "";
}

frame.addEventListener("mousemove", (event) => {
  onPointer(event.clientX, event.clientY);
});

frame.addEventListener("mouseleave", resetPose);

frame.addEventListener(
  "touchstart",
  (event) => {
    const touch = event.changedTouches[0];
    onPointer(touch.clientX, touch.clientY);
  },
  { passive: true }
);

frame.addEventListener(
  "touchmove",
  (event) => {
    const touch = event.changedTouches[0];
    onPointer(touch.clientX, touch.clientY);
    if (active) event.preventDefault();
  },
  { passive: false }
);

frame.addEventListener("touchend", resetPose);
frame.addEventListener("touchcancel", resetPose);

window.addEventListener("pagehide", () => {
  if (pending === 0 || sending) return;
  const body = new Blob([JSON.stringify({ count: pending })], {
    type: "application/json",
  });
  if (navigator.sendBeacon("/api/pats", body)) pending = 0;
});

pull();
setInterval(pull, 4000);
