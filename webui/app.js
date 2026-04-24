const VIEW_FILTERS = {
  ALL: "all",
  GIFT: "gift",
};

const AUTO_SCROLL_THRESHOLD_PX = 24;

const state = {
  messages: [],
  maxItems: 200,
  activeFilter: VIEW_FILTERS.ALL,
  countdownSeconds: 60,
  countdownTimer: null,
  isCounting: false,
};

const elements = {
  messageList: document.getElementById("messageList"),
  clearButton: document.getElementById("clearButton"),
  template: document.getElementById("messageTemplate"),
  filterButtons: Array.from(document.querySelectorAll("[data-view-filter]")),
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

function getLatestMessage() {
  if (!state.messages.length) {
    return null;
  }
  return state.messages[state.messages.length - 1];
}

function messageMatchesFilter(item, filter = state.activeFilter) {
  if (filter === VIEW_FILTERS.GIFT) {
    return item?.type === "gift";
  }
  return true;
}

function getVisibleMessages() {
  return state.messages.filter((item) => messageMatchesFilter(item));
}

function getMessageTypeLabel(type) {
  const labels = {
    chat: "聊天",
    gift: "礼物",
    like: "点赞",
  };
  return labels[type] || "消息";
}

function getMessageContent(item) {
  if (item.type === "gift") {
    const parsedName = String(item.content || "").match(/送(?:出(?:了)?|了)?\s*([^xX×*\s，。,.!！]+)/);
    const giftName = item.gift_name || (parsedName ? parsedName[1] : "礼物");
    const giftCount = Number(item.gift_count || item.combo_count || item.repeat_count || 1);
    return `送出了 ${giftName} x${giftCount}`;
  }
  if (item.type === "like") {
    const count = Number(item.count || 0);
    const total = Number(item.total || 0);
    const likeText = count > 0 ? `点了 ${count} 个赞` : "点了赞";
    return total > 0 ? `${likeText} · 直播间累计 ${total}` : likeText;
  }
  return item.content || "";
}

function getEmptyStateContent() {
  if (state.activeFilter === VIEW_FILTERS.GIFT) {
    return {
      title: "等待礼物消息",
      description: "当前为仅看礼物视图。直播间出现送礼或粉丝团礼物类消息后，会实时显示在这里。",
      ariaLabel: "礼物消息列表",
    };
  }

  return {
    title: "等待直播消息",
    description: "聊天、礼物和点赞事件会实时显示在这里，倒计时结束后会选中最新一条消息的用户。",
    ariaLabel: "实时聊天消息",
  };
}

function updateFilterButtons() {
  elements.filterButtons.forEach((button) => {
    const isActive = button.dataset.viewFilter === state.activeFilter;
    button.classList.toggle("is-active", isActive);
    button.setAttribute("aria-pressed", String(isActive));
  });

  const { ariaLabel } = getEmptyStateContent();
  elements.messageList.setAttribute("aria-label", ariaLabel);
}

function getMessageListGap() {
  return Number.parseFloat(getComputedStyle(elements.messageList).rowGap || getComputedStyle(elements.messageList).gap || "0") || 0;
}

function isMessageListNearBottom() {
  const { scrollTop, scrollHeight, clientHeight } = elements.messageList;
  return scrollHeight - clientHeight - scrollTop <= AUTO_SCROLL_THRESHOLD_PX;
}

function createEmptyStateNode() {
  const { title, description } = getEmptyStateContent();
  const empty = document.createElement("div");
  empty.className = "empty-state";
  empty.innerHTML = `
    <div>
      <strong>${title}</strong>
      <p>${description}</p>
    </div>
  `;
  return empty;
}

function createMessageNode(item) {
  const node = elements.template.content.firstElementChild.cloneNode(true);
  node.dataset.kind = item.type || "chat";
  node.querySelector(".message-user").textContent = item.user_name || "匿名用户";
  node.querySelector(".message-kind").textContent = getMessageTypeLabel(item.type);
  node.querySelector(".message-time").textContent = formatTime(item.iso_time || item.timestamp);
  node.querySelector(".message-content").textContent = getMessageContent(item);
  return node;
}

function renderMessages({ forceScrollToBottom = false, preserveScroll = false } = {}) {
  const previousScrollTop = elements.messageList.scrollTop;
  const wasNearBottom = isMessageListNearBottom();
  const shouldScrollToBottom = forceScrollToBottom || (preserveScroll && wasNearBottom);

  updateFilterButtons();

  const visibleMessages = getVisibleMessages();
  if (!visibleMessages.length) {
    elements.messageList.replaceChildren(createEmptyStateNode());
  } else {
    const fragment = document.createDocumentFragment();
    visibleMessages.forEach((item) => {
      fragment.appendChild(createMessageNode(item));
    });
    elements.messageList.replaceChildren(fragment);
  }

  if (shouldScrollToBottom) {
    elements.messageList.scrollTop = elements.messageList.scrollHeight;
  } else if (preserveScroll) {
    const maxScrollTop = Math.max(0, elements.messageList.scrollHeight - elements.messageList.clientHeight);
    elements.messageList.scrollTop = Math.min(previousScrollTop, maxScrollTop);
  }
}

function syncIncrementalMessageList({ item, removedItem, wasNearBottom, previousScrollTop, hadVisibleMessages, hasVisibleMessages }) {
  const itemIsVisible = messageMatchesFilter(item);
  const removedWasVisible = removedItem ? messageMatchesFilter(removedItem) : false;

  if (!hasVisibleMessages) {
    elements.messageList.replaceChildren(createEmptyStateNode());
    return;
  }

  if (!hadVisibleMessages) {
    elements.messageList.replaceChildren(createMessageNode(item));
    return;
  }

  if (!itemIsVisible && !removedWasVisible) {
    return;
  }

  let removedHeight = 0;
  if (removedWasVisible && elements.messageList.firstElementChild) {
    const firstChild = elements.messageList.firstElementChild;
    removedHeight = firstChild.getBoundingClientRect().height + getMessageListGap();
    firstChild.remove();
  }

  if (itemIsVisible) {
    elements.messageList.appendChild(createMessageNode(item));
  }

  if (wasNearBottom) {
    elements.messageList.scrollTop = elements.messageList.scrollHeight;
  } else if (removedWasVisible) {
    elements.messageList.scrollTop = Math.max(0, previousScrollTop - removedHeight);
  } else {
    elements.messageList.scrollTop = previousScrollTop;
  }
}

function setActiveFilter(filter) {
  if (!Object.values(VIEW_FILTERS).includes(filter)) {
    return;
  }
  state.activeFilter = filter;
  renderMessages({ preserveScroll: true });
}

function addMessage(item) {
  const wasNearBottom = isMessageListNearBottom();
  const previousScrollTop = elements.messageList.scrollTop;
  const hadVisibleMessages = getVisibleMessages().length > 0;
  const removedItem = state.messages.length >= state.maxItems ? state.messages[0] : null;

  state.messages.push(item);
  if (state.messages.length > state.maxItems) {
    state.messages = state.messages.slice(-state.maxItems);
  }

  const hasVisibleMessages = getVisibleMessages().length > 0;
  syncIncrementalMessageList({
    item,
    removedItem,
    wasNearBottom,
    previousScrollTop,
    hadVisibleMessages,
    hasVisibleMessages,
  });
}

function hydrateMessages(items) {
  state.messages = Array.isArray(items) ? items.slice(-state.maxItems) : [];
  renderMessages({ forceScrollToBottom: true });
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
  elements.countdownStatus.textContent = `倒计时结束，已选中最新一条${getMessageTypeLabel(latest.type)}用户：${userName}`;
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
  elements.countdownStatus.textContent = "倒计时开始，结束后将读取当前最新一条聊天、礼物或点赞消息的用户。";
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
  const messagesResponse = await fetch("/api/messages");
  const messages = await messagesResponse.json();
  hydrateMessages(messages.items);
}

function connectEvents() {
  const source = new EventSource("/events");
  source.addEventListener("packet", (event) => {
    console.debug("直播消息包", JSON.parse(event.data));
  });
  source.addEventListener("unknown_message", (event) => {
    console.debug("未识别直播消息", JSON.parse(event.data));
  });
  source.addEventListener("parse_error", (event) => {
    console.warn("直播消息解析失败", JSON.parse(event.data));
  });
  source.addEventListener("chat", (event) => {
    addMessage(JSON.parse(event.data));
  });
  source.addEventListener("gift", (event) => {
    addMessage(JSON.parse(event.data));
  });
  source.addEventListener("like", (event) => {
    addMessage(JSON.parse(event.data));
  });
}

elements.clearButton.addEventListener("click", () => {
  state.messages = [];
  renderMessages({ forceScrollToBottom: true });
});

elements.filterButtons.forEach((button) => {
  button.addEventListener("click", () => {
    setActiveFilter(button.dataset.viewFilter);
  });
});

elements.countdownButton.addEventListener("click", startCountdown);

updateFilterButtons();
resetCountdownUI();
loadInitialData()
  .then(connectEvents)
  .catch((error) => {
    elements.messageList.replaceChildren();
    elements.messageList.innerHTML = `
      <div class="empty-state">
        <div>
          <strong>初始化失败</strong>
          <p>${error.message}</p>
        </div>
      </div>
    `;
  });
