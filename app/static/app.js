/**
 * Persona AI — Interactive Web Frontend
 * Handles real-time burst message delays, audio synthesized sound effects,
 * vector status syncing, and drag-and-drop chat export uploads.
 */

// ── State ────────────────────────────────────────────────────────────────────
const state = {
  personaName: "Rahul",
  history: [],
  soundEnabled: true,
  isGenerating: false,
};

// ── DOM References ───────────────────────────────────────────────────────────
const elements = {
  messagesContainer: document.getElementById("messagesContainer"),
  chatInput: document.getElementById("chatInput"),
  sendBtn: document.getElementById("sendBtn"),
  quickPrompts: document.getElementById("quickPrompts"),
  soundToggle: document.getElementById("soundToggle"),
  soundIcon: document.getElementById("soundIcon"),
  clearChatBtn: document.getElementById("clearChatBtn"),
  
  // HUD Elements
  avatarText: document.getElementById("avatarText"),
  headerAvatar: document.getElementById("headerAvatar"),
  targetName: document.getElementById("targetName"),
  headerName: document.getElementById("headerName"),
  indexedCount: document.getElementById("indexedCount"),
  hinglishStat: document.getElementById("hinglishStat"),
  slangCount: document.getElementById("slangCount"),
  slangChips: document.getElementById("slangChips"),
  typingIndicatorText: document.getElementById("typingIndicatorText"),
  
  // Modal Elements
  uploadModal: document.getElementById("uploadModal"),
  openUploadBtn: document.getElementById("openUploadBtn"),
  closeModalBtn: document.getElementById("closeModalBtn"),
  cancelUploadBtn: document.getElementById("cancelUploadBtn"),
  dropZone: document.getElementById("dropZone"),
  fileInput: document.getElementById("fileInput"),
  fileNamePreview: document.getElementById("fileNamePreview"),
  uploadForm: document.getElementById("uploadForm"),
  modalTargetPerson: document.getElementById("modalTargetPerson"),
  modalFormat: document.getElementById("modalFormat"),
  submitUploadBtn: document.getElementById("submitUploadBtn"),
  uploadLoader: document.getElementById("uploadLoader"),
  uploadStatusBox: document.getElementById("uploadStatusBox"),
  progressBar: document.getElementById("progressBar"),
  uploadStatusMsg: document.getElementById("uploadStatusMsg"),
};

// ── Web Audio Synthesizer (Zero asset dependencies) ──────────────────────────
let audioCtx = null;

function getAudioContext() {
  if (!audioCtx) {
    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  }
  if (audioCtx.state === "suspended") {
    audioCtx.resume();
  }
  return audioCtx;
}

function playSound(type) {
  if (!state.soundEnabled) return;
  try {
    const ctx = getAudioContext();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);

    const now = ctx.currentTime;

    if (type === "send") {
      osc.type = "sine";
      osc.frequency.setValueAtTime(440, now);
      osc.frequency.exponentialRampToValueAtTime(880, now + 0.08);
      gain.gain.setValueAtTime(0.12, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.08);
      osc.start(now);
      osc.stop(now + 0.08);
    } else if (type === "receive") {
      osc.type = "sine";
      osc.frequency.setValueAtTime(780, now);
      osc.frequency.exponentialRampToValueAtTime(520, now + 0.12);
      gain.gain.setValueAtTime(0.15, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.12);
      osc.start(now);
      osc.stop(now + 0.12);
    }
  } catch (e) {
    // AudioContext permission fallback
  }
}

// ── Status Syncing ───────────────────────────────────────────────────────────
async function fetchPersonaStatus() {
  try {
    const res = await fetch("/api/persona-status");
    if (!res.ok) return;
    const data = await res.json();

    if (data.persona_name) {
      state.personaName = data.persona_name;
      elements.targetName.textContent = data.persona_name;
      elements.headerName.textContent = data.persona_name;
      const initial = data.persona_name.charAt(0).toUpperCase();
      elements.avatarText.textContent = initial;
      elements.headerAvatar.textContent = initial;
    }

    elements.indexedCount.textContent = data.indexed_pairs || 0;

    if (data.profile) {
      if (data.profile.hinglish_ratio) {
        elements.hinglishStat.textContent = data.profile.hinglish_ratio.split(" ")[0] || "60/40";
      }

      if (data.profile.slang && data.profile.slang.length > 0) {
        elements.slangCount.textContent = `${data.profile.slang.length} active`;
        elements.slangChips.innerHTML = data.profile.slang
          .slice(0, 8)
          .map(s => `<span class="chip">${s}</span>`)
          .join("");
      }
    }
  } catch (err) {
    console.warn("Could not load persona status:", err);
  }
}

// ── Chat Actions ─────────────────────────────────────────────────────────────

function formatTime() {
  const now = new Date();
  return now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function appendUserMessage(text) {
  const row = document.createElement("div");
  row.className = "message-row user";
  row.innerHTML = `
    <div class="burst-group">
      <div class="bubble user-bubble">
        ${escapeHtml(text)}
        <span class="msg-meta">${formatTime()}</span>
      </div>
    </div>
  `;
  elements.messagesContainer.appendChild(row);
  scrollToBottom();
  playSound("send");
}

function showTypingIndicator() {
  const typingRow = document.createElement("div");
  typingRow.className = "message-row persona";
  typingRow.id = "activeTypingIndicator";
  typingRow.innerHTML = `
    <div class="avatar-wrap xs">
      <div class="avatar xs">${state.personaName.charAt(0).toUpperCase()}</div>
    </div>
    <div class="burst-group">
      <div class="bubble persona-bubble typing-bubble">
        <span class="typing-dot"></span>
        <span class="typing-dot"></span>
        <span class="typing-dot"></span>
      </div>
    </div>
  `;
  elements.messagesContainer.appendChild(typingRow);
  elements.typingIndicatorText.textContent = "typing...";
  scrollToBottom();
  return typingRow;
}

function removeTypingIndicator() {
  const el = document.getElementById("activeTypingIndicator");
  if (el) el.remove();
  elements.typingIndicatorText.textContent = "online";
}

async function renderPersonaBursts(messages, delays_ms) {
  removeTypingIndicator();

  const row = document.createElement("div");
  row.className = "message-row persona";
  row.innerHTML = `
    <div class="avatar-wrap xs">
      <div class="avatar xs">${state.personaName.charAt(0).toUpperCase()}</div>
    </div>
    <div class="burst-group" id="currentBurstGroup"></div>
  `;
  elements.messagesContainer.appendChild(row);
  const burstGroup = row.querySelector("#currentBurstGroup");

  for (let i = 0; i < messages.length; i++) {
    const delay = delays_ms[i] || 250;
    
    // Show typing state between bursts
    elements.typingIndicatorText.textContent = "typing...";
    await new Promise(resolve => setTimeout(resolve, delay));

    const bubble = document.createElement("div");
    bubble.className = "bubble persona-bubble";
    bubble.style.animation = "slideUp 0.22s cubic-bezier(0.16, 1, 0.3, 1)";
    bubble.innerHTML = `
      ${escapeHtml(messages[i])}
      <span class="msg-meta">${formatTime()}</span>
    `;
    burstGroup.appendChild(bubble);
    playSound("receive");
    scrollToBottom();
  }

  elements.typingIndicatorText.textContent = "online";
}

async function sendMessage(text) {
  if (!text || state.isGenerating) return;
  state.isGenerating = true;

  appendUserMessage(text);
  elements.chatInput.value = "";
  elements.chatInput.style.height = "auto";

  showTypingIndicator();

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: text,
        history: state.history.slice(-6),
      }),
    });

    if (!res.ok) {
      const rawError = await res.text();
      let errorMsg = rawError || "Generation failed";
      try {
        const err = JSON.parse(rawError);
        if (err && err.detail) {
          errorMsg = typeof err.detail === "string" ? err.detail : JSON.stringify(err.detail);
        }
      } catch {
        // use rawError text
      }
      throw new Error(errorMsg);
    }

    const data = await res.json();
    await renderPersonaBursts(data.messages, data.delays_ms);

    // Track history
    state.history.push({ role: "user", content: text });
    state.history.push({ role: "assistant", content: data.messages.join(" ") });

  } catch (err) {
    removeTypingIndicator();
    const errorBubble = document.createElement("div");
    errorBubble.className = "message-row persona";
    errorBubble.innerHTML = `
      <div class="burst-group">
        <div class="bubble persona-bubble" style="border-color: var(--accent-rose); color: #fda4af;">
          ⚠️ Error: ${escapeHtml(err.message)}
        </div>
      </div>
    `;
    elements.messagesContainer.appendChild(errorBubble);
    scrollToBottom();
  } finally {
    state.isGenerating = false;
  }
}

function scrollToBottom() {
  elements.messagesContainer.scrollTop = elements.messagesContainer.scrollHeight;
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

// ── Upload Modal Logic ───────────────────────────────────────────────────────

function openModal() {
  elements.uploadModal.classList.add("active");
  elements.modalTargetPerson.value = state.personaName || "";
}

function closeModal() {
  elements.uploadModal.classList.remove("active");
  elements.uploadStatusBox.style.display = "none";
  elements.uploadLoader.style.display = "none";
  elements.submitUploadBtn.disabled = false;
}

let selectedFile = null;

elements.dropZone.addEventListener("click", () => elements.fileInput.click());

elements.fileInput.addEventListener("change", (e) => {
  if (e.target.files.length > 0) {
    selectedFile = e.target.files[0];
    elements.fileNamePreview.textContent = `Selected: ${selectedFile.name} (${Math.round(selectedFile.size / 1024)} KB)`;
  }
});

elements.dropZone.addEventListener("dragover", (e) => {
  e.preventDefault();
  elements.dropZone.classList.add("dragover");
});

elements.dropZone.addEventListener("dragleave", () => {
  elements.dropZone.classList.remove("dragover");
});

elements.dropZone.addEventListener("drop", (e) => {
  e.preventDefault();
  elements.dropZone.classList.remove("dragover");
  if (e.dataTransfer.files.length > 0) {
    selectedFile = e.dataTransfer.files[0];
    elements.fileNamePreview.textContent = `Selected: ${selectedFile.name} (${Math.round(selectedFile.size / 1024)} KB)`;
  }
});

elements.uploadForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!selectedFile) {
    alert("Please choose or drop a chat export file first.");
    return;
  }

  const target = elements.modalTargetPerson.value.trim();
  if (!target) return;

  const formData = new FormData();
  formData.append("file", selectedFile);
  formData.append("target_person", target);
  formData.append("format", elements.modalFormat.value);
  formData.append("auto_profile", "true");

  elements.submitUploadBtn.disabled = true;
  elements.uploadLoader.style.display = "inline-block";
  elements.uploadStatusBox.style.display = "block";
  elements.progressBar.style.width = "40%";
  elements.uploadStatusMsg.textContent = "Parsing dialogues & sanitizing sensitive PII...";

  try {
    const res = await fetch("/api/upload-chat", {
      method: "POST",
      body: formData,
    });

    elements.progressBar.style.width = "85%";
    elements.uploadStatusMsg.textContent = "Extracting persona habits & indexing vector memory...";

    if (!res.ok) {
      const rawError = await res.text();
      let errorMsg = rawError || "Upload failed";
      try {
        const err = JSON.parse(rawError);
        if (err && err.detail) {
          errorMsg = typeof err.detail === "string" ? err.detail : JSON.stringify(err.detail);
        }
      } catch {
        // use rawError text
      }
      throw new Error(errorMsg);
    }

    const data = await res.json();
    elements.progressBar.style.width = "100%";
    elements.uploadStatusMsg.textContent = `✓ Success! Indexed ${data.indexed_pairs} memory pairs for ${data.target_person}.`;

    if (data.target_person) {
      state.personaName = data.target_person;
      elements.targetName.textContent = data.target_person;
      elements.headerName.textContent = data.target_person;
      const initial = data.target_person.charAt(0).toUpperCase();
      elements.avatarText.textContent = initial;
      elements.headerAvatar.textContent = initial;
    }

    setTimeout(async () => {
      closeModal();
      await fetchPersonaStatus();
    }, 1200);

  } catch (err) {
    elements.progressBar.style.backgroundColor = "var(--accent-rose)";
    elements.uploadStatusMsg.textContent = `Error: ${err.message}`;
    elements.submitUploadBtn.disabled = false;
    elements.uploadLoader.style.display = "none";
  }
});

// ── Event Listeners ──────────────────────────────────────────────────────────

elements.sendBtn.addEventListener("click", () => {
  const text = elements.chatInput.value.trim();
  sendMessage(text);
});

elements.chatInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    const text = elements.chatInput.value.trim();
    sendMessage(text);
  }
});

// Auto-expand textarea
elements.chatInput.addEventListener("input", function () {
  this.style.height = "auto";
  this.style.height = Math.min(this.scrollHeight, 120) + "px";
});

// Quick prompt chips
elements.quickPrompts.addEventListener("click", (e) => {
  const chip = e.target.closest(".prompt-chip");
  if (chip) {
    const text = chip.dataset.text || chip.textContent;
    sendMessage(text);
  }
});

// Sound Toggle
elements.soundToggle.addEventListener("click", () => {
  state.soundEnabled = !state.soundEnabled;
  elements.soundToggle.style.opacity = state.soundEnabled ? "1" : "0.4";
});

// Clear Chat
elements.clearChatBtn.addEventListener("click", () => {
  state.history = [];
  elements.messagesContainer.innerHTML = `
    <div class="encryption-notice">
      <span>🔒 Chat cleared. Persona memory intact.</span>
    </div>
  `;
});

// Modal Toggles
elements.openUploadBtn.addEventListener("click", openModal);
elements.closeModalBtn.addEventListener("click", closeModal);
elements.cancelUploadBtn.addEventListener("click", closeModal);

// ── Init ─────────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  fetchPersonaStatus();
});
