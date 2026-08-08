/* Agent Orchestrator — Audio Notification ("Ting" Chime) */

let _audioCtx = null;
let _soundEnabled = true;
let _lastTingTime = 0;

// Khởi tạo / resume AudioContext khi có tương tác đầu tiên
function getAudioContext() {
  const AudioCtx = window.AudioContext || window.webkitAudioContext;
  if (!AudioCtx) return null;
  if (!_audioCtx) {
    _audioCtx = new AudioCtx();
  }
  if (_audioCtx.state === "suspended") {
    _audioCtx.resume();
  }
  return _audioCtx;
}

// Bắt sự kiện tương tác đầu tiên để unlock Web Audio API
if (typeof window !== "undefined") {
  const unlockAudio = () => {
    getAudioContext();
    window.removeEventListener("click", unlockAudio);
    window.removeEventListener("keydown", unlockAudio);
    window.removeEventListener("touchstart", unlockAudio);
  };
  window.addEventListener("click", unlockAudio, { passive: true });
  window.addEventListener("keydown", unlockAudio, { passive: true });
  window.addEventListener("touchstart", unlockAudio, { passive: true });
}

/**
 * Phát âm thanh "ting" nhẹ, trong trẻo khi subtask hoặc task hoàn thành.
 * Tạo bằng Web Audio API thuần (dual-harmonic crystal bell chime), không cần file ngoài.
 */
export function playTing(reason = "complete") {
  if (!_soundEnabled) return;
  const now = Date.now();
  // Debounce 350ms tránh dồn dập nếu nhiều event tới cùng lúc
  if (now - _lastTingTime < 350) return;
  _lastTingTime = now;

  try {
    const ctx = getAudioContext();
    if (!ctx) return;

    const t = ctx.currentTime;

    // 1. Primary crystal tone (C6 -> E6 trượt nhẹ 1046.5Hz -> 1318.5Hz)
    const osc1 = ctx.createOscillator();
    const gain1 = ctx.createGain();
    osc1.type = "sine";
    osc1.frequency.setValueAtTime(1046.5, t);
    osc1.frequency.exponentialRampToValueAtTime(1318.5, t + 0.06);

    gain1.gain.setValueAtTime(0.001, t);
    gain1.gain.linearRampToValueAtTime(0.14, t + 0.012);
    gain1.gain.exponentialRampToValueAtTime(0.0001, t + 0.7);

    osc1.connect(gain1);
    gain1.connect(ctx.destination);
    osc1.start(t);
    osc1.stop(t + 0.72);

    // 2. Harmonic shimmer overtone (C7 2093Hz thanh tao)
    const osc2 = ctx.createOscillator();
    const gain2 = ctx.createGain();
    osc2.type = "sine";
    osc2.frequency.setValueAtTime(2093.0, t);

    gain2.gain.setValueAtTime(0.001, t);
    gain2.gain.linearRampToValueAtTime(0.06, t + 0.012);
    gain2.gain.exponentialRampToValueAtTime(0.0001, t + 0.45);

    osc2.connect(gain2);
    gain2.connect(ctx.destination);
    osc2.start(t);
    osc2.stop(t + 0.48);

    // Hiệu ứng rung chuông trên Bell icon
    triggerBellAnimation();
  } catch (err) {
    console.debug("playTing error:", err);
  }
}

export function triggerBellAnimation() {
  const bell = document.getElementById("bell-btn");
  if (!bell) return;
  bell.classList.remove("ringing");
  // Force reflow
  void bell.offsetWidth;
  bell.classList.add("ringing");
  setTimeout(() => bell.classList.remove("ringing"), 600);
}

export function toggleSound() {
  _soundEnabled = !_soundEnabled;
  if (_soundEnabled) {
    playTing("test");
  }
  const bell = document.getElementById("bell-btn");
  if (bell) {
    bell.title = _soundEnabled ? "Âm thanh thông báo: Bật (Nhấp để tắt)" : "Âm thanh thông báo: Tắt (Nhấp để bật)";
    bell.classList.toggle("sound-muted", !_soundEnabled);
  }
  return _soundEnabled;
}

export function isSoundEnabled() {
  return _soundEnabled;
}
