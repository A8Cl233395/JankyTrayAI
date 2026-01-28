const { createApp, ref, onMounted, nextTick, onBeforeUnmount, watch } = Vue;

const API_BASE = "http://localhost:3417";

createApp({
    setup() {
        // --- 状态变量 ---
        const isSidebarCollapsed = ref(false);
        const inputText = ref("");
        const inputImages = ref([]); // 存储 base64 字符串
        const messages = ref([]); // 当前聊天记录
        const historyList = ref([]); // 左侧历史列表
        const currentChatId = ref(null); // 当前会话ID
        
        const isGenerating = ref(false); // 是否正在生成/接收流
        const isLoadingHistory = ref(false); // 是否正在加载历史
        
        let abortController = null; // 用于中断请求
        let aliveInterval = null; // 用于保活心跳
        
        // --- 辅助引用 ---
        const chatContainer = ref(null);
        const inputBox = ref(null);
        const historyContainer = ref(null);

        // --- 初始化 Markdown 解析器 ---
        marked.setOptions({
            highlight: function(code, lang) {
                const language = hljs.getLanguage(lang) ? lang : 'plaintext';
                return hljs.highlight(code, { language }).value;
            },
            langPrefix: 'hljs language-'
        });

        // --- API 请求封装 ---
        const apiFetch = async (url, options = {}) => {
            try {
                const res = await fetch(`${API_BASE}${url}`, options);
                if (!res.ok) throw new Error(`API Error: ${res.status}`);
                return res;
            } catch (e) {
                console.error(e);
                alert("网络请求失败，请检查控制台");
                throw e;
            }
        };

        // --- 图片处理 (JPEG 压缩) ---
        const compressImage = (file) => {
            return new Promise((resolve, reject) => {
                const reader = new FileReader();
                reader.readAsDataURL(file);
                reader.onload = (event) => {
                    const img = new Image();
                    img.src = event.target.result;
                    img.onload = () => {
                        const canvas = document.createElement('canvas');
                        const ctx = canvas.getContext('2d');
                        canvas.width = img.width;
                        canvas.height = img.height;
                        ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
                        // 压缩为 jpeg 0.8
                        resolve(canvas.toDataURL('image/jpeg', 0.8));
                    };
                    img.onerror = reject;
                };
                reader.onerror = reject;
            });
        };

        const handleImageUpload = async (e) => {
            const files = Array.from(e.target.files);
            for (const file of files) {
                try {
                    const base64 = await compressImage(file);
                    inputImages.value.push(base64);
                } catch (err) {
                    console.error("图片压缩失败", err);
                }
            }
            e.target.value = ''; // 重置 input
        };

        const removeImage = (index) => {
            inputImages.value.splice(index, 1);
        };

        // --- 输入框自适应 ---
        const autoResizeInput = () => {
            const el = inputBox.value;
            el.style.height = 'auto';
            el.style.height = el.scrollHeight + 'px';
        };

        const handleEnterKey = (e) => {
            if (!e.shiftKey) {
                sendMessage();
            }
        };

        // --- 历史记录逻辑 ---
        
        // 加载初始历史列表
        const loadHistoryList = async () => {
            const res = await apiFetch("/get");
            const data = await res.json();
            // 假设返回按ID从大到小排序
            historyList.value = data; 
        };

    // 切换对话前的保存与清理
        const saveCurrentChat = async () => {
            if (currentChatId.value) {
                if (aliveInterval) clearInterval(aliveInterval);
                try {
                    // 显式使用 fetch 确保在切换时能发出请求，并等待其完成
                    await fetch(`${API_BASE}/save?id=${currentChatId.value}`);
                } catch (e) {
                    console.error("保存对话失败:", e);
                }
            }
        };

        // 加载特定对话
        const loadChat = async (id) => {
            if (currentChatId.value === id) return;
            
            // 如果正在生成，不允许切换，或者需要先中断
            if (isGenerating.value) {
                if(!confirm("当前正在生成内容，切换将中断，确定吗？")) return;
                abortController.abort();
                isGenerating.value = false;
            }

            await saveCurrentChat();
            
            currentChatId.value = id;
            messages.value = [];
            
            // 获取历史详情
            const res = await apiFetch(`/get?id=${id}`);
            const rawMessages = await res.json();
            
            // 解析历史消息格式适配前端
            // 后端返回: [{"role":"user", content: [...]}, {"role": "assistant", "content": "xxx"}]
            // 前端需要: {role, text, images[], think, isThinkingCollapsed}
            
            messages.value = rawMessages.map(msg => {
                const uiMsg = { role: msg.role, text: '', images: [], think: '', isThinkingCollapsed: true };
                
                if (msg.role === 'user') {
                    // 处理 User 的 content 数组
                    if (Array.isArray(msg.content)) {
                        msg.content.forEach(item => {
                            if (item.type === 'text') uiMsg.text += item.text;
                            if (item.type === 'image_url') uiMsg.images.push(item.image_url.url);
                        });
                    } else {
                        uiMsg.text = msg.content; // 兼容旧数据
                    }
                } else if (msg.role === 'assistant') {
                     // 简单处理：假设历史记录里的 content 是纯文本 Markdown
                     // 如果历史记录里也包含了思考过程的标记，需要更复杂的解析，
                     // 这里假设历史记录返回的是最终的 content 文本
                     uiMsg.text = msg.content;
                } else if (msg.role === 'tool') {
                    uiMsg.content = msg.content; // 工具调用名或结果
                }
                return uiMsg;
            });

            scrollToBottom();
            startAliveLoop(id);
        };

        // 开始新对话
        const startNewChat = async () => {
            // 如果正在生成，需要先中断并停止状态
            if (isGenerating.value) {
                if(!confirm("当前正在生成内容，开始新对话将中断，确定吗？")) return;
                abortController.abort();
                isGenerating.value = false;
            }

            await saveCurrentChat();
            
            currentChatId.value = null;
            messages.value = [];
            inputText.value = "";
            inputImages.value = [];
            if (aliveInterval) clearInterval(aliveInterval);
        };

        // 无限滚动逻辑 (Pagination)
        const handleHistoryScroll = async (e) => {
            const { scrollTop, scrollHeight, clientHeight } = e.target;
            
            // 触底加载更早的 (below)
            if (scrollHeight - scrollTop - clientHeight < 10) {
                if (historyList.value.length === 0 || isLoadingHistory.value) return;
                const lastId = historyList.value[historyList.value.length - 1].id;
                
                isLoadingHistory.value = true;
                try {
                    const res = await apiFetch(`/get?below=${lastId}`);
                    const more = await res.json();
                    if (more.length > 0) {
                        historyList.value.push(...more);
                    }
                } finally {
                    isLoadingHistory.value = false;
                }
            }

            // 触顶加载更新的 (above) - 视需求，一般新对话会自动插在最前
            if (scrollTop < 10 && historyList.value.length > 0) {
                const firstId = historyList.value[0].id;
                // 这里可以实现检查有没有新产生的对话（比如在其他设备产生的）
                // const res = await apiFetch(`/get?above=${firstId}`);
            }
        };

        // --- 核心：发送与流式接收 ---
        const sendMessage = async () => {
            if (isGenerating.value) {
                // 如果正在生成，点击按钮则是“停止”
                abortController.abort();
                isGenerating.value = false;
                return;
            }

            const text = inputText.value.trim();
            if (!text && inputImages.value.length === 0) return;

            // 1. 构建用户消息并显示
            const userContent = [];
            inputImages.value.forEach(url => {
                userContent.push({ type: "image_url", image_url: { url } });
            });
            if (text) {
                userContent.push({ type: "text", text });
            }

            messages.value.push({
                role: 'user',
                text: text,
                images: [...inputImages.value]
            });

            // 清空输入
            inputText.value = "";
            inputImages.value = [];
            nextTick(() => autoResizeInput()); // 重置高度
            scrollToBottom();

            // 2. 准备请求
            isGenerating.value = true;
            abortController = new AbortController();

            const payload = { content: userContent };
            if (currentChatId.value) {
                payload.id = currentChatId.value;
            }

            try {
                const response = await fetch(`${API_BASE}/generate`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                    signal: abortController.signal
                });

                if (!response.ok) throw new Error("Generation failed");

                // 3. 准备接收 AI 回复
                // 创建一个空的 assistant 消息占位
                const currentMsgIndex = messages.value.length;
                messages.value.push({
                    role: 'assistant',
                    text: '',
                    think: '',
                    isThinkingCollapsed: false,
                    isStreaming: true
                });

                const reader = response.body.getReader();
                const decoder = new TextDecoder();
                let buffer = "";
                let currentSignal = 0; // 默认为回答

                // 4. 读取流
                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;

                    buffer += decoder.decode(value, { stream: true });
                    const lines = buffer.split('\n');
                    buffer = lines.pop(); // 保留最后一个可能不完整的片段

                    for (const line of lines) {
                        if (line.trim().startsWith('data: ')) {
                            try {
                                const jsonStr = line.replace('data: ', '').trim();
                                if (!jsonStr) continue;
                                const data = JSON.parse(jsonStr);

                                // --- 处理各种 SSE 字段 ---
                                
                                // 处理 ID (如果是新对话)
                                if (data.id && !currentChatId.value) {
                                    currentChatId.value = data.id;
                                    startAliveLoop(data.id);
                                    // 临时添加到历史列表顶部，直到有标题
                                    historyList.value.unshift({ id: data.id, title: "新对话" });
                                }

                                // 处理 Title
                                if (data.title) {
                                    const chatItem = historyList.value.find(h => h.id === currentChatId.value);
                                    if (chatItem) chatItem.title = data.title;
                                }

                                // 处理 Signal 切换
                                if (data.signal !== undefined) {
                                    currentSignal = data.signal;
                                    
                                    // 信号 3: 工具调用，创建一个独立的消息块
                                    if (currentSignal === 3) {
                                        messages.value.pop(); // 移除刚才那个还在流式传输的 assistant 块（如果为空的话）或者截断
                                        // 注意：为了简化，这里假设 signal 3 是一次性的或者独立的
                                        messages.value.push({
                                            role: 'tool',
                                            content: data.name || "Unknown Tool"
                                        });
                                        // 重新加回 assistant 块准备接下来的输出
                                        messages.value.push({
                                            role: 'assistant',
                                            text: '',
                                            think: '',
                                            isThinkingCollapsed: false,
                                            isStreaming: true
                                        });
                                    }
                                }

                                // 处理 Data 内容
                                if (data.data) {
                                    const activeMsg = messages.value[messages.value.length - 1];
                                    if (activeMsg.role !== 'assistant') continue; // 防止错位

                                    if (currentSignal === 1) {
                                        // 思考内容
                                        activeMsg.think += data.data;
                                    } else if (currentSignal === 0) {
                                        // 正式回答
                                        // 如果之前是在思考，现在切回回答，且思考未折叠，可以考虑自动折叠（可选）
                                        // activeMsg.isThinkingCollapsed = true; 
                                        activeMsg.text += data.data;
                                    }
                                    
                                    scrollToBottom();
                                }

                            } catch (e) {
                                console.error("Parse error", e);
                            }
                        }
                    }
                }

            } catch (err) {
                if (err.name !== 'AbortError') {
                    console.error(err);
                    messages.value.push({ role: 'assistant', text: "\n[出错: 连接断开]" });
                }
            } finally {
                isGenerating.value = false;
                if (messages.value.length > 0) {
                    messages.value[messages.value.length - 1].isStreaming = false;
                }
            }
        };

        // --- 心跳保活 ---
        const startAliveLoop = (id) => {
            if (aliveInterval) clearInterval(aliveInterval);
            aliveInterval = setInterval(() => {
                fetch(`${API_BASE}/alive?id=${id}`).catch(console.error);
            }, 10000);
        };

        // --- 界面工具 ---
        const toggleSidebar = () => {
            isSidebarCollapsed.value = !isSidebarCollapsed.value;
        };

        const renderMarkdown = (text) => {
            return marked.parse(text || "");
        };

        const scrollToBottom = () => {
            nextTick(() => {
                if (chatContainer.value) {
                    chatContainer.value.scrollTop = chatContainer.value.scrollHeight;
                }
            });
        };

        // --- 生命周期 ---
        onMounted(() => {
            loadHistoryList();
            
            window.addEventListener('visibilitychange', () => {
                if (document.visibilityState === 'hidden' && currentChatId.value) {
                    // 页面隐藏/关闭时使用 sendBeacon 最可靠（注意后端需支持 POST）
                    navigator.sendBeacon(`${API_BASE}/save?id=${currentChatId.value}`);
                }
            });
        });

        onBeforeUnmount(() => {
            if (aliveInterval) clearInterval(aliveInterval);
        });

        return {
            isSidebarCollapsed,
            toggleSidebar,
            historyList,
            messages,
            inputText,
            inputImages,
            isGenerating,
            isLoadingHistory,
            currentChatId,
            chatContainer,
            inputBox,
            historyContainer,
            startNewChat,
            loadChat,
            sendMessage,
            handleEnterKey,
            handleImageUpload,
            removeImage,
            autoResizeInput,
            renderMarkdown,
            handleHistoryScroll
        };
    }
}).mount('#app');