/**
 * agent/web/app.js - 前端交互、SSE 流式接收与极简时序渲染引擎
 * 
 * 特性：
 * 1. 严格遵循行业时序共识：内容自顶向下顺序排列，最新的工具调用或文本永远在最下方；
 * 2. 工具调用展示无卡片、无背景：仅显示“正在执行 xxx”呼吸渐变文字与展开小箭头，默认折叠；
 * 3. 杜绝 Emoji：全量使用极简内联矢量 SVG 图标；
 * 4. 健壮的 SSE 流式打字机解析与 Markdown 实时渲染。
 */

// -----------------------------------------------------------------------------
// 1. 全局状态与 DOM 引用
// -----------------------------------------------------------------------------
let currentSessionId = 'session_' + Math.random().toString(36).substring(2, 9);
let isStreaming = false;

const chatContainer = document.getElementById('chat-container');
const messagesList = document.getElementById('messages-list');
const chatInput = document.getElementById('chat-input');
const btnSend = document.getElementById('btn-send');
const btnNewChat = document.getElementById('btn-new-chat');
const btnClearAll = document.getElementById('btn-clear-all');
const welcomeHero = document.getElementById('welcome-hero');
const workspacePathText = document.getElementById('workspace-path-text');
const currentThreadId = document.getElementById('current-thread-id');
const sessionList = document.getElementById('session-list');

if (currentThreadId) {
  currentThreadId.textContent = currentSessionId;
}

// -----------------------------------------------------------------------------
// 2. 极简 SVG 图标模板 (杜绝 Emoji)
// -----------------------------------------------------------------------------
const ICONS = {
  // AI 头像图标 (简约星茫/算法标记)
  aiAvatar: `
    <svg class="w-4 h-4 text-[#d96528]" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
      <path stroke-linecap="round" stroke-linejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z"/>
    </svg>
  `,
  // 折叠小箭头 (向右，展开时旋转90度向下)
  chevron: `
    <svg class="tool-chevron w-3.5 h-3.5 text-[#8a877c]" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
      <path stroke-linecap="round" stroke-linejoin="round" d="M9 5l7 7-7 7"/>
    </svg>
  `,
  // 工具执行完成对勾
  check: `
    <svg class="w-3 h-3 text-emerald-600 inline-block shrink-0" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24">
      <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7"/>
    </svg>
  `,
  // 工具执行异常警告
  error: `
    <svg class="w-3 h-3 text-rose-600 inline-block shrink-0" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24">
      <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/>
    </svg>
  `,
  // 耗时计时器图标
  timer: `
    <svg class="w-3 h-3 text-[#8a877c]" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
      <circle cx="12" cy="12" r="9"/>
      <path stroke-linecap="round" stroke-linejoin="round" d="M12 7v5l3 3"/>
    </svg>
  `,
  // Token 芯片图标
  chip: `
    <svg class="w-3 h-3 text-[#8a877c]" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
      <path stroke-linecap="round" stroke-linejoin="round" d="M9 3v2m6-2v2M9 19v2m6-2v2M3 9h2m-2 6h2m14-6h2m-2 6h2M7 5h10a2 2 0 012 2v10a2 2 0 01-2 2H7a2 2 0 01-2-2V7a2 2 0 012-2z"/>
    </svg>
  `
};

// 工具名友好显示映射
function getFriendlyToolName(toolName) {
  const map = {
    'bash': '运行命令 (bash)',
    'write': '写入文件 (write)',
    'read': '读取文件 (read)',
    'edit': '编辑文件 (edit)',
    'list_workspace_files': '检索工作区文件',
    'search_academic_literature': '检索学术文献',
    'generate_mermaid_diagram': '生成架构图'
  };
  return map[toolName] || toolName;
}

// -----------------------------------------------------------------------------
// 3. 初始化与信息加载
// -----------------------------------------------------------------------------
async function initSystemInfo() {
  try {
    const res = await fetch('/api/info');
    if (!res.ok) return;
    const data = await res.json();
    if (workspacePathText) {
      workspacePathText.textContent = data.workspace_path || '未知路径';
      workspacePathText.title = data.workspace_path;
    }
    const badge = document.getElementById('model-badge');
    if (badge) {
      badge.textContent = data.model ? `${data.model} 在线` : 'Agent 1 在线';
    }
  } catch (err) {
    console.warn('获取系统信息失败:', err);
  }
}

initSystemInfo();

// -----------------------------------------------------------------------------
// 4. 会话与交互控制
// -----------------------------------------------------------------------------
function startNewChat() {
  currentSessionId = 'session_' + Math.random().toString(36).substring(2, 9);
  if (currentThreadId) {
    currentThreadId.textContent = currentSessionId;
  }
  const sessionTitle = document.getElementById('current-session-title');
  if (sessionTitle) {
    sessionTitle.textContent = '新会话';
  }
  messagesList.innerHTML = '';
  if (welcomeHero) {
    welcomeHero.style.display = 'block';
  }
  chatInput.value = '';
  chatInput.focus();
}

if (btnNewChat) {
  btnNewChat.addEventListener('click', startNewChat);
}

if (btnClearAll) {
  btnClearAll.addEventListener('click', async () => {
    if (confirm('确定要清空所有会话历史吗？')) {
      try {
        await fetch('/api/sessions/clear', { method: 'POST' });
      } catch (e) {}
      startNewChat();
    }
  });
}

// 快捷提示词点击绑定
document.querySelectorAll('.quick-prompt').forEach(card => {
  card.addEventListener('click', () => {
    const titleEl = card.querySelector('.prompt-title');
    const title = titleEl ? titleEl.textContent.trim() : '';
    if (title.includes('创建标准毕业论文模板')) {
      chatInput.value = '请清空默认样式并为我创建一个标准规范的毕业论文演示文档 test/my_paper_template.docx，包含三级标题、1.5倍行距、首行缩进正文与规范三线表。';
    } else if (title.includes('构建中国学术规范三线表')) {
      chatInput.value = '请在 Word 中生成一个符合高校学术规范的标准三线表（顶线底线1.5pt，栏目线0.75pt，表内无竖线）。';
    } else if (title.includes('检查已有模板规范')) {
      chatInput.value = '请使用 read 与 bash 工具检查工作区已有 Word 模板的段落字体、行间距与 OpenXML 结构。';
    } else if (title.includes('深度解析样式')) {
      chatInput.value = '请向我详细分析毕业论文正文中首行缩进2字符 (24pt) 与 1.5倍行距在底层 styles.xml 中的正确配置方法。';
    }
    sendMessage();
  });
});

// 输入框回车监听
chatInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});

btnSend.addEventListener('click', sendMessage);

// -----------------------------------------------------------------------------
// 5. 核心：消息发送与严格流式时序渲染 (最新在最下方)
// -----------------------------------------------------------------------------
async function sendMessage() {
  const text = chatInput.value.trim();
  if (!text || isStreaming) return;

  if (welcomeHero) {
    welcomeHero.style.display = 'none';
  }
  chatInput.value = '';
  isStreaming = true;
  btnSend.disabled = true;

  // 1. 追加用户消息
  appendUserMessage(text);
  scrollToBottom();

  // 2. 创建当前轮次 AI 消息容器
  const aiMessageElement = createAIMessageShell();
  messagesList.appendChild(aiMessageElement);
  scrollToBottom();

  const streamContent = aiMessageElement.querySelector('.stream-content');
  const metricsBar = aiMessageElement.querySelector('.metrics-bar');

  // 时序状态追踪器：
  // 当需要追加文本时，若当前末尾非活跃文本块，则新建一个文本块并追加到 streamContent 最底部；
  // 当调用工具时，重置当前文本块引用，将工具行追加到 streamContent 最底部；
  // 确保持续调用工具或工具前后交织时，所有内容均按时间轴严格自顶向下排列！
  let activeTextDiv = null;
  let activeTextRaw = '';
  let activeToolItems = {}; // key: toolName, value: domElement

  try {
    const response = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text, session_id: currentSessionId }),
    });

    if (!response.ok) {
      throw new Error(`网络请求异常: HTTP ${response.status} ${response.statusText}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop(); // 保持尾部未完成行

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed.startsWith('data:')) continue;

        const jsonStr = trimmed.substring(5).trim();
        if (!jsonStr) continue;

        try {
          const eventData = JSON.parse(jsonStr);

          // -------------------------------------------------------------------
          // A. 文本流增量 (text_delta)
          // -------------------------------------------------------------------
          if (eventData.type === 'text_delta') {
            if (!activeTextDiv) {
              // 在流式内容的最底部创建新的 Markdown 文本容器
              activeTextDiv = document.createElement('div');
              activeTextDiv.className = 'prose-custom text-[#34322d] text-sm leading-relaxed';
              streamContent.appendChild(activeTextDiv);
              activeTextRaw = '';
            }
            activeTextRaw += eventData.content;
            activeTextDiv.innerHTML = marked.parse(activeTextRaw);
            activeTextDiv.querySelectorAll('pre code').forEach(el => hljs.highlightElement(el));
            scrollToBottom();
          }

          // -------------------------------------------------------------------
          // B. 工具开始调用 (tool_start) -> 插入最新行至最下方
          // -------------------------------------------------------------------
          else if (eventData.type === 'tool_start') {
            // 工具调用产生，打断先前的文本流块，使后续文本在新的一块中输出
            activeTextDiv = null;
            activeTextRaw = '';

            const toolName = eventData.tool || 'tool';
            const friendlyName = getFriendlyToolName(toolName);
            const toolItem = createToolItemElement(toolName, friendlyName, eventData.input);
            
            // 严格挂载在当前内容的最底部（若持续调用工具，后调用的自然在下方）
            streamContent.appendChild(toolItem);
            activeToolItems[toolName] = toolItem;
            scrollToBottom();
          }

          // -------------------------------------------------------------------
          // C. 工具执行完毕 (tool_end) -> 更新状态并填充折叠详情
          // -------------------------------------------------------------------
          else if (eventData.type === 'tool_end') {
            const toolName = eventData.tool || 'tool';
            const toolItem = activeToolItems[toolName];
            if (toolItem) {
              updateToolItemCompletion(toolItem, toolName, eventData.output);
            }
            scrollToBottom();
          }

          // -------------------------------------------------------------------
          // D. 性能与消耗指标 (metrics) -> 底部胶囊
          // -------------------------------------------------------------------
          else if (eventData.type === 'metrics') {
            renderMetrics(metricsBar, eventData);
          }

          // -------------------------------------------------------------------
          // E. 执行异常或中断 (error)
          // -------------------------------------------------------------------
          else if (eventData.type === 'error') {
            const errDiv = document.createElement('div');
            errDiv.className = 'py-2 px-3 rounded-lg bg-rose-50/70 border-l-2 border-rose-500 text-rose-800 text-xs my-2 leading-relaxed';
            errDiv.innerHTML = marked.parse(eventData.message);
            streamContent.appendChild(errDiv);
            scrollToBottom();
          }

        } catch (err) {
          console.error('SSE JSON 解析错误:', err, jsonStr);
        }
      }
    }

  } catch (err) {
    const errDiv = document.createElement('div');
    errDiv.className = 'py-2 px-3 rounded-lg bg-rose-50/70 border-l-2 border-rose-500 text-rose-800 text-xs my-2 leading-relaxed';
    errDiv.textContent = `通信异常: ${err.message}`;
    streamContent.appendChild(errDiv);
  } finally {
    isStreaming = false;
    btnSend.disabled = false;
    chatInput.focus();
  }
}

// -----------------------------------------------------------------------------
// 6. DOM 元素构造器 (极简无背景、无卡片、纯文字渐变动效与折叠详情)
// -----------------------------------------------------------------------------

function appendUserMessage(content) {
  const msgDiv = document.createElement('div');
  msgDiv.className = 'flex justify-end';
  msgDiv.innerHTML = `
    <div class="max-w-[85%] rounded-2xl bg-[#33312b] text-[#fbfbfa] px-4 py-2.5 text-sm shadow-xs leading-relaxed">
      ${escapeHtml(content).replace(/\n/g, '<br>')}
    </div>
  `;
  messagesList.appendChild(msgDiv);
}

function createAIMessageShell() {
  const wrapper = document.createElement('div');
  wrapper.className = 'flex items-start space-x-3 text-sm';
  wrapper.innerHTML = `
    <div class="w-7 h-7 rounded-xl bg-[#d96528]/10 flex items-center justify-center shrink-0 mt-0.5 border border-[#d96528]/20">
      ${ICONS.aiAvatar}
    </div>
    <div class="flex-1 min-w-0 space-y-3">
      <!-- 严格顺序时间线流容器 (最新在最下方) -->
      <div class="stream-content space-y-2.5"></div>

      <!-- 底部耗时与 Token 统计 -->
      <div class="metrics-bar text-[11px] text-[#8a877c] pt-0.5 flex items-center space-x-3"></div>
    </div>
  `;
  return wrapper;
}

/**
 * 创建工具调用行 (无卡片容器、无背景，仅文字呼吸渐变动效与折叠箭头，默认折叠)
 */
function createToolItemElement(toolName, friendlyName, inputParams) {
  const container = document.createElement('div');
  container.className = 'tool-item py-1 select-none text-xs';

  const inputFormatted = typeof inputParams === 'object'
    ? JSON.stringify(inputParams, null, 2)
    : String(inputParams || '');

  container.innerHTML = `
    <button class="tool-header-btn group" type="button">
      ${ICONS.chevron}
      <span class="tool-status-label breathing-gradient font-medium text-xs">正在执行 ${escapeHtml(friendlyName)}...</span>
    </button>
    <div class="tool-detail-panel" style="display: none;">
      <div class="tool-detail-section">
        <div class="tool-detail-label">输入参数</div>
        <div class="tool-detail-content tool-input-content">${escapeHtml(inputFormatted)}</div>
      </div>
      <div class="tool-detail-section">
        <div class="tool-detail-label">输出结果</div>
        <div class="tool-detail-content tool-output-content text-[#8a877c] italic">执行中，等待结果输出...</div>
      </div>
    </div>
  `;

  // 展开/折叠交互 (默认折叠)
  const headerBtn = container.querySelector('.tool-header-btn');
  const chevron = container.querySelector('.tool-chevron');
  const detailPanel = container.querySelector('.tool-detail-panel');

  headerBtn.addEventListener('click', () => {
    const isHidden = detailPanel.style.display === 'none';
    detailPanel.style.display = isHidden ? 'block' : 'none';
    if (isHidden) {
      chevron.classList.add('expanded');
    } else {
      chevron.classList.remove('expanded');
    }
  });

  return container;
}

/**
 * 更新工具执行完成状态 (停止呼吸渐变，替换状态文字并填入输出结果)
 */
function updateToolItemCompletion(toolItem, toolName, outputText) {
  const statusLabel = toolItem.querySelector('.tool-status-label');
  const outputContent = toolItem.querySelector('.tool-output-content');
  const friendlyName = getFriendlyToolName(toolName);

  const isFailed = outputText.includes('【工具执行失败') || outputText.includes('Error:') || outputText.includes('Traceback');

  if (statusLabel) {
    // 移除呼吸渐变动效，切换为静态完成/异常样式
    statusLabel.classList.remove('breathing-gradient');
    if (isFailed) {
      statusLabel.className = 'tool-status-label font-medium text-xs text-rose-600 flex items-center gap-1.5';
      statusLabel.innerHTML = `${ICONS.error} <span>执行异常 ${escapeHtml(friendlyName)}</span>`;
    } else {
      statusLabel.className = 'tool-status-label font-medium text-xs text-[#78756c] flex items-center gap-1.5';
      statusLabel.innerHTML = `${ICONS.check} <span>已完成 ${escapeHtml(friendlyName)}</span>`;
    }
  }

  if (outputContent) {
    outputContent.classList.remove('italic', 'text-[#8a877c]');
    outputContent.textContent = outputText || '(空输出)';
  }
}

/**
 * 渲染底部性能胶囊 (采用极简矢量 SVG 图标)
 */
function renderMetrics(container, data) {
  container.innerHTML = `
    <span class="inline-flex items-center space-x-1.5 px-2 py-0.5 rounded-md bg-[#eeebe2]/60 text-[#78756c]">
      ${ICONS.timer}
      <span>耗时: <strong class="font-medium text-[#3b3935]">${data.duration}s</strong></span>
    </span>
    <span class="inline-flex items-center space-x-1.5 px-2 py-0.5 rounded-md bg-[#eeebe2]/60 text-[#78756c]">
      ${ICONS.chip}
      <span>Tokens: <strong class="font-medium text-[#3b3935]">${data.total_tokens}</strong> (入: ${data.prompt_tokens} / 出: ${data.completion_tokens})</span>
    </span>
  `;
}

// -----------------------------------------------------------------------------
// 7. 工具辅助函数
// -----------------------------------------------------------------------------
function scrollToBottom() {
  chatContainer.scrollTop = chatContainer.scrollHeight;
}

function escapeHtml(str) {
  if (typeof str !== 'string') return '';
  return str.replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
}

