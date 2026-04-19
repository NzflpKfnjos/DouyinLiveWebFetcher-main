const state = {
  messages: [],
  maxItems: 200,
  countdownSeconds: 60,
  countdownTimer: null,
  isCounting: false,
};

const elements = {
  messageList: document.getElementById("messageList"),
  clearButton: document.getElementById("clearButton"),
  template: document.getElementById("messageTemplate"),
  countdownButton: document.getElementById("countdownButton"),
  countdownDisplay: document.getElementById("countdownDisplay"),
  countdownStatus: document.getElementById("countdownStatus"),
  winnerDisplay: document.getElementById("winnerDisplay"),
  drawResult: document.querySelector(".draw-result"),
};

function formatTime(value) {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleTimeString("zh-CN", {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function getInitials(name) {
  const value = (name || "匿名").trim();
  return Array.from(value).slice(0, 2).join("").toUpperCase();
}

function getLatestMessage() {
  if (!state.messages.length) {
    return null;
  }
  return state.messages[state.messages.length - 1];
}

function getMessageTypeLabel(type) {
  return type === "gift" ? "礼物" : "聊天";
}

function getMessageContent(item) {
  if (item.type === "gift") {
    if (item.content) {
      return item.content;
    }
    const giftName = item.gift_name || "礼物";
    const giftCount = item.gift_count || 1;
    return `送出 ${giftName} x${giftCount}`;
  }
  return item.content || "";
}

function renderEmptyState() {
  const empty = document.createElement("div");
  empty.className = "empty-state";
  empty.innerHTML = `
    <div>
      <strong>等待直播消息</strong>
      <p>聊天和礼物事件会实时显示在这里，倒计时结束后会选中最新一条消息的用户。</p>
    </div>
  `;
  elements.messageList.appendChild(empty);
}

function renderMessages() {
  elements.messageList.innerHTML = "";

  if (!state.messages.length) {
    renderEmptyState();
    return;
  }

  const fragment = document.createDocumentFragment();
  state.messages.forEach((item) => {
    const node = elements.template.content.firstElementChild.cloneNode(true);
    node.dataset.kind = item.type || "chat";
    node.querySelector(".message-avatar").textContent = getInitials(item.user_name);
    node.querySelector(".message-user").textContent = item.user_name || "匿名用户";
    node.querySelector(".message-kind").textContent = getMessageTypeLabel(item.type);
    node.querySelector(".message-time").textContent = formatTime(item.iso_time || item.timestamp);
    node.querySelector(".message-content").textContent = getMessageContent(item);
    fragment.appendChild(node);
  });

  elements.messageList.appendChild(fragment);
  elements.messageList.scrollTop = elements.messageList.scrollHeight;
}

function addMessage(item) {
  state.messages.push(item);
  if (state.messages.length > state.maxItems) {
    state.messages = state.messages.slice(-state.maxItems);
  }
  renderMessages();
}

function hydrateMessages(items) {
  state.messages = Array.isArray(items) ? items.slice(-state.maxItems) : [];
  renderMessages();
}

function resetCountdownUI() {
  elements.countdownDisplay.textContent = String(state.countdownSeconds);
  elements.countdownButton.textContent = `开始 ${state.countdownSeconds} 秒倒计时`;
  elements.countdownButton.disabled = false;
}

function finishCountdown() {
  window.clearInterval(state.countdownTimer);
  state.countdownTimer = null;
  state.isCounting = false;

  const latest = getLatestMessage();
  elements.winnerDisplay.classList.remove("is-rolling");

  if (!latest) {
    elements.winnerDisplay.textContent = "无人";
    elements.countdownStatus.textContent = "倒计时结束，但当前没有可用的直播消息。";
    resetCountdownUI();
    return;
  }

  const userName = latest.user_name || "匿名用户";
  elements.winnerDisplay.textContent = userName;
  elements.countdownStatus.textContent = `倒计时结束，已选中最新一条消息用户：${userName}`;
  elements.drawResult.classList.remove("is-winner");
  void elements.drawResult.offsetWidth;
  elements.drawResult.classList.add("is-winner");
  resetCountdownUI();
}

function startCountdown() {
  if (state.isCounting) {
    return;
  }

  state.isCounting = true;
  let remaining = state.countdownSeconds;
  elements.countdownDisplay.textContent = String(remaining);
  elements.countdownButton.disabled = true;
  elements.countdownButton.textContent = `倒计时中 ${remaining}s`;
  elements.countdownStatus.textContent = "倒计时开始，结束后将读取当前最新一条消息的用户。";
  elements.winnerDisplay.classList.add("is-rolling");

  state.countdownTimer = window.setInterval(() => {
    remaining -= 1;
    elements.countdownDisplay.textContent = String(Math.max(remaining, 0));
    elements.countdownButton.textContent = `倒计时中 ${Math.max(remaining, 0)}s`;

    const latest = getLatestMessage();
    if (latest) {
      elements.winnerDisplay.textContent = latest.user_name || "匿名用户";
    } else {
      elements.winnerDisplay.textContent = "等待消息";
    }

    if (remaining <= 0) {
      finishCountdown();
    }
  }, 1000);
}

async function loadInitialData() {
  const response = await fetch("/api/messages");
  const messages = await response.json();
  hydrateMessages(messages.items);
}

function connectEvents() {
  const source = new EventSource("/events");
  ["chat", "gift"].forEach((eventName) => {
    source.addEventListener(eventName, (event) => {
      addMessage(JSON.parse(event.data));
    });
  });
}

elements.clearButton.addEventListener("click", () => {
  state.messages = [];
  renderMessages();
});

elements.countdownButton.addEventListener("click", startCountdown);

resetCountdownUI();
loadInitialData()
  .then(connectEvents)
  .catch((error) => {
    elements.messageList.innerHTML = `
      <div class="empty-state">
        <div>
          <strong>初始化失败</strong>
          <p>${error.message}</p>
        </div>
      </div>
    `;
  });
