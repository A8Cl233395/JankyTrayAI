from individual_modules import *

class MainWindow:
    def __init__(self, width=200, height=300, shift=10, taskbar_height=60):
        self.root = tk.Tk()
        self.root.title("托盘小工具")
        self.root.attributes('-topmost', True)  # 永远置顶
        self.root.protocol('WM_DELETE_WINDOW', self.root.withdraw)
        self.root.bind('<Unmap>', lambda event: self.root.withdraw())
        # self.root.overrideredirect(True)
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = screen_width - width - shift
        y = screen_height - height - shift - taskbar_height
        self.root.geometry(f'{width}x{height}+{x}+{y}')
        self.display_area = scrolledtext.ScrolledText(
            self.root,
            wrap=tk.WORD,
            font=('微软雅黑', 10),
            height=10,
        )
        self.display_area.pack(fill=tk.BOTH, expand=True, side=tk.TOP)
        self.input_area = scrolledtext.ScrolledText(
            self.root,
            wrap=tk.WORD,
            font=('微软雅黑', 10),
            height=3,
        )
        self.input_area.pack(fill=tk.BOTH, expand=False, side=tk.BOTTOM)
        self.input_area.bind('<Return>', self.on_enter_key)  # Enter键
        self.input_area.bind('<Control-Return>', lambda e: self.send_message())  # Ctrl+Enter

        if not os.path.exists('saves/histories'):
            os.makedirs('saves/histories')

        is_db_exist = os.path.exists('saves/history_titles.db')
        self.conn = sqlite3.connect('saves/history_titles.db', check_same_thread=False, timeout=5)
        with self.conn:
            cursor = self.conn.cursor()
            if not is_db_exist:
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS titles (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        title TEXT
                    )
                ''')
                cursor.execute("PRAGMA journal_mode = WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA busy_timeout = 3417")
            cursor.execute("PRAGMA cache_size = -64000")
        self.history_titles = []
        self.history_cache = LRUCache(50)

        self.last_active_window = None
        self.manual_extra_data = []

        self.last_clipboard_data = []
        self.current_chat_index = -1

        self.is_feature_screenshot_enable = False
        self.is_feature_clipboard_enable = False
        self.is_feature_browser_backend_enable = False
        self.is_feature_web_server_enable = False
        self.main_model = "deepseek-chat"
        self.assist_model = "qwen-flash"
        self.vision_model = "qwen3-vl-plus-2025-12-19"

        if os.path.exists('saves/settings.json'):
            with open('saves/settings.json', 'r', encoding='utf-8') as f:
                settings = json.load(f)
            del f
            self.is_feature_screenshot_enable = settings["is_feature_screenshot_enable"]
            self.is_feature_clipboard_enable = settings["is_feature_clipboard_enable"]
            self.is_feature_browser_backend_enable = settings["is_feature_browser_backend_enable"]
            self.is_feature_web_server_enable = settings["is_feature_web_server_enable"]
            self.main_model = settings["main_model"]
            self.assist_model = settings["assist_model"]
            self.vision_model = settings["vision_model"]
        
        if self.is_feature_screenshot_enable:
            self.get_active_window_thread = threading.Thread(target=self._get_active_window_loop)
            self.get_active_window_thread.daemon = True
            self.get_active_window_thread.start()
        
        if self.is_feature_browser_backend_enable:
            self.browser_backend = WebServer(self)
            self.browser_backend.run_server()
        
        if self.is_feature_web_server_enable:
            from server import _run_server
            self.web_server = multiprocessing.Process(target=_run_server, args=(self.main_model, self.vision_model, self.assist_model))
            self.web_server.daemon = True
            self.web_server.start()
        
        self.display_area.tag_configure("user", foreground="#2563eb")
        self.display_area.tag_configure("assistant", foreground="#059669")
        self.display_area.tag_configure("thinking", foreground="#6b7280")
        self.display_area.tag_configure("answering", foreground="#dc2626")

    def insert_message(self, message: str, tag: str | None = None):
        """插入消息到显示区域"""
        if tag:
            self.display_area.insert(tk.END, message, tag)
        else:
            self.display_area.insert(tk.END, message)

    def on_enter_key(self, event):
        if event.state & 0x0001:  # Shift被按住
            # 允许默认行为（换行），不调用send_message
            return 
        self.send_message()
        return 'break'  # 阻止默认行为

    def send_message(self):
        """发送消息"""
        if hasattr(self, 'generate_response_thread') and self.generate_response_thread.is_alive():
            self.display_area.see(tk.END)  # 滚动到最新消息
            return
        user_input = self.input_area.get("1.0", tk.END).strip()
        self.input_area.delete("1.0", tk.END)  # 清空输入框
        if user_input:
            self.insert_message(f"你: ", "user")
            self.insert_message(user_input+"\n")
            if not hasattr(self, 'chatinstance'):
                if self.current_chat_index != -1: # 已选择历史记录，懒加载，不初始化
                    self.new_chat()
                else:
                    self.new_chat(user_input)
            self.display_area.see(tk.END)  # 滚动到最新消息
            self.generate_response_thread = threading.Thread(target=self._generate_and_insert_response, args=(user_input,))
            self.generate_response_thread.start()

    def _generate_and_insert_response(self, user_input: str):
        self.chatinstance.new()
        self.auto_add_extra_data()
        self.chatinstance.add({"type": "text", "text": user_input})
        self.chatinstance.merge()
        self.insert_message(f"AI: ", "assistant")
        self.chatinstance()
        self.insert_message("\n")

    def _generate_and_insert_chat_title(self, user_input: str):
        title = ask_ai("你是一个专业的对话标题生成器，你需要根据用户的输入生成一句对话标题。", user_input, model=self.assist_model, prefix="```标题\n", stop="\n```")
        with self.conn:
            cursor = self.conn.cursor()
            cursor.execute("UPDATE titles SET title = ? WHERE id = ?", (title, self.current_chat_index))
        if hasattr(self, 'history_listbox'):
            self.history_listbox.delete(0)
            self.history_listbox.insert(0, title)
    
    def open_settings(self):
        if hasattr(self, 'settings_root'):  # 如果窗口已打开
            self.settings_root.deiconify()  # 显示窗口
            return
        self.settings_root = tk.Toplevel(self.root)
        self.settings_root.title("设置")
        self.settings_root.attributes('-topmost', True)
        self.settings_root.geometry(f'200x300+{self.root.winfo_x()-200}+{self.root.winfo_y()}')
        # self.settings_root.overrideredirect(True)
        self.settings_root.protocol("WM_DELETE_WINDOW", self.settings_root.withdraw)
        self.settings_root.bind('<Unmap>', lambda event: self.settings_root.withdraw())
        
        is_feature_screenshot_enable = tk.BooleanVar(value=self.is_feature_screenshot_enable)
        self.checkbox_screenshot = ttk.Checkbutton(self.settings_root, text="自动添加焦点窗口截图", variable=is_feature_screenshot_enable, command=lambda: self._set_feature_screenshot(is_feature_screenshot_enable.get()))
        self.checkbox_screenshot.pack(pady=5)

        is_feature_clipboard_enable = tk.BooleanVar(value=self.is_feature_clipboard_enable)
        self.checkbox_clipboard = ttk.Checkbutton(self.settings_root, text="自动添加剪贴板内容", variable=is_feature_clipboard_enable, command=lambda: self._set_feature_clipboard(is_feature_clipboard_enable.get()))
        self.checkbox_clipboard.pack(pady=5)

        is_feature_browser_backend_enable = tk.BooleanVar(value=self.is_feature_browser_backend_enable)
        self.checkbox_browser_backend = ttk.Checkbutton(self.settings_root, text="浏览器后端", variable=is_feature_browser_backend_enable, command=lambda: self._set_feature_browser_backend(is_feature_browser_backend_enable.get()))
        self.checkbox_browser_backend.pack(pady=5)

        is_feature_web_server_enable = tk.BooleanVar(value=self.is_feature_web_server_enable)
        self.checkbox_web_server = ttk.Checkbutton(self.settings_root, text="网页模式", variable=is_feature_web_server_enable, command=lambda: self._set_feature_web_server(is_feature_web_server_enable.get()))
        self.checkbox_web_server.pack(pady=5)

        self.entry_main_model = ttk.Entry(self.settings_root, font=('微软雅黑', 10), width=20)
        self.entry_main_model.pack(pady=5)
        self.entry_main_model.insert(0, self.main_model)
        self.entry_main_model.bind('<Return>', lambda event: self._set_main_model(self.entry_main_model.get()))

        self.entry_vision_model = ttk.Entry(self.settings_root, font=('微软雅黑', 10), width=20)
        self.entry_vision_model.pack(pady=5)
        self.entry_vision_model.insert(0, self.vision_model)
        self.entry_vision_model.bind('<Return>', lambda event: self._set_vision_model(self.entry_vision_model.get()))

        self.entry_assist_model = ttk.Entry(self.settings_root, font=('微软雅黑', 10), width=20)
        self.entry_assist_model.pack(pady=5)
        self.entry_assist_model.insert(0, self.assist_model)
        self.entry_assist_model.bind('<Return>', lambda event: self._set_assist_model(self.entry_assist_model.get()))
    
    def _set_feature_web_server(self, enable: bool):
        self.is_feature_web_server_enable = enable
        trayicon.set_menu_shortcut(enable)
        if enable:
            if not hasattr(globals(), '_run_server'):
                from server import _run_server
            self.web_server: multiprocessing.Process = multiprocessing.Process(target=_run_server, args=(self.main_model, self.vision_model, self.assist_model))
            self.web_server.daemon = True
            self.web_server.start()
        else:
            if hasattr(self, 'web_server'):
                self.web_server.terminate()
                self.web_server.join(timeout=1)
                del self.web_server
    
    def _set_feature_browser_backend(self, enable: bool):
        self.is_feature_browser_backend_enable = enable
        if enable:
            if not hasattr(self, 'browser_backend'):
                self.browser_backend = WebServer(self)
                self.browser_backend.run_server()
            else:
                self.browser_backend.run_server()
        else:
            if hasattr(self, 'browser_backend'):
                self.browser_backend.server.shutdown()
                self.browser_backend.server_thread.join(timeout=1)
                del self.browser_backend
    
    def _set_feature_screenshot(self, enable: bool):
        self.is_feature_screenshot_enable = enable
        if enable:
            if not hasattr(self, 'get_active_window_thread') or not self.get_active_window_thread.is_alive():
                self.get_active_window_thread = threading.Thread(target=self._get_active_window_loop)
                self.get_active_window_thread.daemon = True  # 守护线程，主程序退出时自动退出
                self.get_active_window_thread.start()
    
    def _set_feature_clipboard(self, enable: bool):
        self.is_feature_clipboard_enable = enable
    
    def _set_main_model(self, model: str):
        self.main_model = model
        if hasattr(self, 'web_server'):
            requests.post('http://127.0.0.1:3417/configure', json={'main_model': model})
    
    def _set_vision_model(self, model: str):
        self.vision_model = model
        if hasattr(self, 'web_server'):
            requests.post('http://127.0.0.1:3417/configure', json={'vision_model': model})
    
    def _set_assist_model(self, model: str):
        self.assist_model = model
        if hasattr(self, 'web_server'):
            requests.post('http://127.0.0.1:3417/configure', json={'assist_model': model})
    
    def open_history(self):
        if hasattr(self, 'history_root'):  # 如果窗口已打开
            self.history_root.deiconify()  # 显示窗口
            return
        self.history_root = tk.Toplevel(self.root)
        self.history_root.title("历史记录")
        self.history_root.attributes('-topmost', True)
        self.history_root.geometry(f'200x300+{self.root.winfo_x()-200}+{self.root.winfo_y()}')
        # self.history_root.overrideredirect(True)
        self.history_root.protocol("WM_DELETE_WINDOW", self.history_root.withdraw)
        self.history_root.bind('<Unmap>', lambda event: self.history_root.withdraw())
        self.history_root.bind('<Delete>', self._remove_history)

        self.history_frame = ttk.Frame(self.history_root)
        self.history_frame.pack(fill=tk.BOTH, expand=True)

        self.history_scrollbar = ttk.Scrollbar(self.history_frame)
        self.history_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.history_listbox = tk.Listbox(
            self.history_frame,
            font=("微软雅黑", 10),
            selectmode=tk.SINGLE  # 只能单选
        )
        self.history_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        # 绑定选择事件
        self.history_listbox.bind('<<ListboxSelect>>', self._on_history_select)
        # 加载最后20条记录
        with self.conn:
            cursor = self.conn.cursor()
            cursor.execute("SELECT id, title FROM titles ORDER BY id DESC LIMIT 20")
            self.history_titles = [{'id': row[0], 'title': row[1]} for row in cursor.fetchall()]
            print(self.history_titles)
        for item in self.history_titles:
            self.history_listbox.insert(tk.END, item['title'])
        
        self.history_scrollbar.config(command=self.history_listbox.yview)
        self.history_listbox.config(yscrollcommand=self._on_listbox_yscroll)

    def _on_listbox_yscroll(self, *args):
        """Listbox 调用 Scrollbar 时的回调"""
        self.history_scrollbar.set(*args)
        self._check_scroll_position()

    def _on_scrollbar_scroll(self, *args):
        """Scrollbar 控制 Listbox 滚动时的回调"""
        self.history_listbox.yview(*args)
        self._check_scroll_position()

    def _check_scroll_position(self):
        """检查是否滚动到顶部或底部"""
        first, last = self.history_listbox.yview()
        print(first, last)
        if first <= 0.0:
            with self.conn:
                cursor = self.conn.cursor()
                cursor.execute("SELECT id, title FROM titles WHERE id > ? ORDER BY id ASC LIMIT 20", (self.history_titles[0]['id'],))
                new_titles = [{'id': row[0], 'title': row[1]} for row in cursor.fetchall()]
                for item in new_titles:
                    self.history_listbox.insert(0, item['title'])
                    self.history_titles.insert(0, item)
        elif last >= 1.0:
            with self.conn:
                cursor = self.conn.cursor()
                cursor.execute("SELECT id, title FROM titles WHERE id < ? ORDER BY id DESC LIMIT 20", (self.history_titles[-1]['id'],))
                new_titles = [{'id': row[0], 'title': row[1]} for row in cursor.fetchall()]
                for item in new_titles:
                    self.history_listbox.insert(tk.END, item['title'])
                    self.history_titles.append(item)
    
    def _on_history_select(self, event):
        """列表项被选中时的回调函数"""
        # 获取当前选中的索引
        selection = self.history_listbox.curselection()
        if selection:
            click_index = selection[0]
            self.load_history_and_focus(click_index)
    
    def _remove_history(self, event):
        """删除选中的历史记录"""
        selection = self.history_listbox.curselection()
        if selection:
            print(self.history_titles)
            current_index = selection[0]
            print(current_index)
            self.history_listbox.delete(current_index)
            if hasattr(self, 'chatinstance'):
                del self.chatinstance
            self.display_area.delete(1.0, tk.END)
            path = f'saves/histories/{self.current_chat_index // 1000}/{self.current_chat_index % 1000}'
            if os.path.exists(path):
                os.remove(path)
            with self.conn:
                cursor = self.conn.cursor()
                cursor.execute("DELETE FROM titles WHERE id = ?", (self.history_titles[current_index]['id'],))
            del self.history_titles[current_index]
            self.current_chat_index = -1

    def load_history_and_focus(self, click_index: int):
        if self.history_titles[click_index]['id'] == self.current_chat_index:
            self.display_area.see(tk.END)  # 滚动到最新消息
            return
        if hasattr(self, 'generate_response_thread') and self.generate_response_thread.is_alive():
            self.display_area.see(tk.END)  # 滚动到最新消息
            return
        if hasattr(self, 'chatinstance'):
            self.archive_and_delete_chat()
        self.current_chat_index = self.history_titles[click_index]['id']
        messages = self.history_cache.get(self.current_chat_index)
        if not messages:
            with open(f'saves/histories/{self.current_chat_index // 1000}/{self.current_chat_index % 1000}', 'r', encoding='utf-8') as f:
                messages = json.load(f)
            self.history_cache.put(self.current_chat_index, messages)
        self.display_area.delete(1.0, tk.END)
        for message in messages:
            if message["role"] == "user":
                text = message['content'][-1]['text']
                text = text.rsplit("额外内容结束\n---\n", 1)[1] if "额外内容结束\n---\n" in text else text
                self.insert_message(f"你: ", "user")
                self.insert_message(text+"\n")
            else:
                self.insert_message(f"AI: ", "assistant")
                self.insert_message(message['content']+"\n")
    
    def toggle_show(self):
        if self.root.state() == 'normal':
            self.root.withdraw()
        else:
            self.root.deiconify()
    
    def new_chat(self, user_input = None):
        if user_input:
            self.chatinstance = ChatInstance(self.main_model, mainwindow=self)
            with self.conn:
                cursor = self.conn.cursor()
                cursor.execute("INSERT INTO titles (title) VALUES (?)", ("新对话",))
                self.current_chat_index = cursor.lastrowid
            self.history_titles.insert(0, {'id': self.current_chat_index, 'title': "新对话"})
            if hasattr(self, 'history_listbox') and self.history_listbox.winfo_exists():
                self.history_listbox.insert(0, self.history_titles[0]['title'])
            threading.Thread(target=self._generate_and_insert_chat_title, args=(user_input,)).start()
        else:
            self.chatinstance = ChatInstance(self.main_model, self.history_cache.get(self.current_chat_index), mainwindow=self)

    def archive_and_delete_chat(self):
        if hasattr(self, "chatinstance"):
            messages = self.chatinstance.messages
            del self.chatinstance
            folder = self.current_chat_index // 1000
            if not os.path.exists(f'saves/histories/{folder}'):
                os.makedirs(f'saves/histories/{folder}')
            with open(f'saves/histories/{folder}/{self.current_chat_index % 1000}', 'w', encoding='utf-8') as f:
                json.dump(messages, f, ensure_ascii=False)

    def on_newchat(self):
        self.archive_and_delete_chat()
        self.display_area.delete(1.0, tk.END)
        self.current_chat_index = -1
    
    def open_add_multimedia(self):
        if hasattr(self, 'add_window'):  # 如果窗口已打开
            self.add_window.deiconify()  # 显示窗口
            return
        add_window = threading.Thread(target=self._create_add_window)
        add_window.daemon = True  # 守护线程，主程序退出时自动退出
        add_window.start()

    def _create_add_window(self):
        self.add_window = TkinterDnD.Tk()
        self.add_window.title("添加多媒体")
        self.add_window.attributes('-topmost', True)
        self.add_window.geometry(f'200x300+{self.root.winfo_x()-200}+{self.root.winfo_y()}')

        self.add_window.bind('<Unmap>', lambda event: self.add_window.withdraw())
        self.add_window.protocol("WM_DELETE_WINDOW", self.add_window.withdraw)
        self.add_window.bind('<Control-v>', self._manual_add_clipboard_data)
        self.add_window.bind('<Delete>', self._remove_add_data)

        self.add_frame = ttk.Frame(self.add_window)
        self.add_frame.pack(fill=tk.BOTH, expand=True)

        self.add_scrollbar = ttk.Scrollbar(self.add_frame)
        self.add_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.add_listbox = tk.Listbox(
            self.add_frame,
            yscrollcommand=self.add_scrollbar.set,
            font=("微软雅黑", 10),
            selectmode=tk.SINGLE  # 只能单选
        )
        self.add_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.add_scrollbar.config(command=self.add_listbox.yview)
        self.add_frame.drop_target_register(DND_FILES)
        self.add_frame.dnd_bind('<<Drop>>', lambda event: threading.Thread(target=self.on_drop, args=(event,)).start())
        self.add_frame.dnd_bind('<<DropEnter>>', self.on_drag_enter)
        self.add_frame.dnd_bind('<<DropLeave>>', self.on_drag_leave)
        if self.manual_extra_data:
            for i in self.manual_extra_data:
                self.add_listbox.insert(tk.END, i["description"])
        self.add_window.mainloop()
    
    def on_drag_enter(self, event):
        self.add_listbox.config(bg="#f0f0ff")

    def on_drag_leave(self, event):
        self.add_listbox.config(bg="white")

    def on_drop(self, event):
        self.add_listbox.config(bg="white")
        data = event.data
        if data:
            pattern = r"\{([^}]+)\}|([^{}\s]+)"
            matches = re.findall(pattern, data)
            result = [m[0] if m[0] else m[1] for m in matches]
            for file_path in result:
                if not os.path.isfile(file_path):
                    continue
                if file_path.split(".")[-1] in ["zip", "rar", "7z", "tar", "gz", "bz2", "svg", "png", "jpg", "jpeg", "gif", "bmp", "mp3", "wav", "mp4", "flac", "mkv", "mov", "exe", "db", "dll"]:
                    self.manual_extra_data.append({"description": "文件: " + file_path.split("/")[-1][:30], "content": {"type": "text", "text": f"```无法读取的文件\n{file_path}\n```"}})
                    self.add_listbox.insert(tk.END, self.manual_extra_data[-1]["description"])
                    continue
                with open(file_path, 'rb') as f:
                    raw_data = f.read(1024)
                detected = chardet.detect(raw_data)
                encoding = detected['encoding']
                confidence = detected['confidence'] # 置信度，0-1之间
                if confidence > 0.8:
                    with open(file_path, 'r', encoding=encoding, errors='replace') as f:
                        text = f.read()
                    filename = file_path.split("/")[-1]
                    self.manual_extra_data.append({"description": "文件: " + filename[:30], "content": {"type": "text", "text": f"```文件: {filename}\n{text}\n```"}})
                    self.add_listbox.insert(tk.END, self.manual_extra_data[-1]["description"])
                else:
                    self.manual_extra_data.append({"description": "文件: " + file_path.split("/")[-1][:30], "content": {"type": "text", "text": f"```无法读取的文件\n{file_path}\n```"}})
                    self.add_listbox.insert(tk.END, self.manual_extra_data[-1]["description"])
    
    def _remove_add_data(self, event):
        selection = self.add_listbox.curselection()
        if selection:
            index = selection[0]
            self.add_listbox.delete(index)
            self.manual_extra_data.pop(index)
    
    def _manual_add_clipboard_data(self, event):
        win32clipboard.OpenClipboard()
        try:
            if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                text = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
                self.manual_extra_data.append({"description": "文本: " + text[:30], "content": {"type": "text", "text": f"```文本\n{text}\n```"}})
                self.add_listbox.insert(tk.END, self.manual_extra_data[-1]["description"])
            elif win32clipboard.IsClipboardFormatAvailable(win32con.CF_DIB):
                image = ImageGrab.grabclipboard()
                if image is not None:
                    self.manual_extra_data.append({"description": "图片", "content": {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_to_b64(image)}"}}})
                    self.add_listbox.insert(tk.END, self.manual_extra_data[-1]["description"])
        except Exception as e:
            print(e)
        finally:
            try:
                win32clipboard.CloseClipboard()
            except:
                pass
    
    def auto_add_extra_data(self):
        current_clipboard_data = []
        if self.is_feature_screenshot_enable:
            image = capture_window_no_border(self.last_active_window)
            if image:
                current_md5 = md5(image.tobytes()).hexdigest()
                if current_md5 not in self.last_clipboard_data:
                    current_clipboard_data.append(current_md5)
                    self.chatinstance.add({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_to_b64(image)}"}})
        if self.is_feature_clipboard_enable:
            win32clipboard.OpenClipboard()
            try:
                if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                    text = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
                    current_md5 = md5(text.encode("utf-8")).hexdigest()
                    current_clipboard_data.append(current_md5)
                    if current_md5 not in self.last_clipboard_data:
                        self.chatinstance.add({"type": "text", "text": f"```自动插入: 剪贴板上的文本\n{text}\n```"})
                elif win32clipboard.IsClipboardFormatAvailable(win32con.CF_DIB):
                    image = ImageGrab.grabclipboard()
                    if image is not None:
                        current_md5 = md5(image.tobytes()).hexdigest()
                        current_clipboard_data.append(current_md5)
                        if current_md5 not in self.last_clipboard_data:
                            self.chatinstance.add({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_to_b64(image)}"}})
            except Exception as e:
                print(e)
            finally:
                try:
                    win32clipboard.CloseClipboard()
                except:
                    pass
        self.last_clipboard_data = current_clipboard_data

        if self.manual_extra_data:
            self.chatinstance.messages[-1]["content"].extend([item["content"] for item in self.manual_extra_data])
            if hasattr(self, 'add_window'): # 处理手动添加的内容
                self.add_listbox.delete(0, tk.END)
            self.manual_extra_data = []
        if self.chatinstance.messages[-1]["content"]:
            self.chatinstance.add({"type": "text", "text": "额外内容结束\n---"})

    def _get_active_window_loop(self):
        while self.is_feature_screenshot_enable:
            active_window = gw.getActiveWindow()
            if active_window and active_window.title not in ["设置", "添加多媒体", "历史记录", "托盘小工具", "", None]:
                self.last_active_window = active_window
            time.sleep(1)

    def __call__(self):
        self.root.mainloop()

    def on_quit(self):
        self.quit_window = tk.Toplevel(self.root)
        self.quit_window.title("退出中...")
        label = ttk.Label(self.quit_window, text="正在保存...")
        label.pack(pady=10)
        if hasattr(self, 'chatinstance'):
            self.archive_and_delete_chat()
        self.conn.close()
        if self.is_feature_web_server_enable:
            requests.get("http://127.0.0.1:3417/archive-all")
        with open("saves/settings.json", "w", encoding="utf-8") as f:
            settings = {
                "is_feature_screenshot_enable": self.is_feature_screenshot_enable,
                "is_feature_clipboard_enable": self.is_feature_clipboard_enable,
                "is_feature_browser_backend_enable": self.is_feature_browser_backend_enable,
                "is_feature_web_server_enable": self.is_feature_web_server_enable,
                "main_model": self.main_model,
                "assist_model": self.assist_model,
                "vision_model": self.vision_model,
            }
            json.dump(settings, f, ensure_ascii=False)
        self.root.after(10, self.root.quit) # 退出 Tkinter

class TrayIcon:
    def __init__(self):
        self.menu = [
            MenuItem("显示", mainwindow.toggle_show, default=True, visible=False),
            MenuItem("新对话", mainwindow.on_newchat),
            MenuItem("添加...", mainwindow.open_add_multimedia),
            MenuItem("历史记录", mainwindow.open_history),
            MenuItem("设置", mainwindow.open_settings),
            MenuItem("退出", self.on_exit)  
        ]
        self.icon = Icon("mini_app", Image.open("icon.png"), menu=Menu(*self.menu))
        self.is_shortcut_exist = False
    
    def on_exit(self):
        """退出程序"""
        self.icon.stop()   # 停止托盘
        mainwindow.on_quit()
    
    def run(self):
        self.icon.run()
    
    def open_browser(self):
        os.system("start http://127.0.0.1:3417")
    
    def set_menu_shortcut(self, show: bool):
        if show:
            if not self.is_shortcut_exist:
                self.menu.insert(3, MenuItem("打开网页", self.open_browser))
                self.is_shortcut_exist = True
        else:
            if self.is_shortcut_exist:
                # 注意：插入位置是索引3，所以“打开网页”在 menu[3]
                # 删除时应删除该元素，而不是 menu[4]
                for i, item in enumerate(self.menu):
                    if item.text == "打开网页":
                        del self.menu[i]
                        break
                self.is_shortcut_exist = False

        # 关键修改：先更新 icon.menu，再调用 update_menu()
        self.icon.menu = Menu(*self.menu)
        self.icon.update_menu()  # 不带参数！

class WebServer:
    def __init__(self, mainwindow: MainWindow):
        self.mainwindow = mainwindow
        self.app = Flask(__name__)
        CORS(self.app)  # 允许跨域请求

        @self.app.route('/receive', methods=['POST'])
        def receive_text():
            # 解析表单数据
            text = request.form.get('text', '')
            url = request.form.get('url', '')
            title = request.form.get('title', '')
            
            print(f"收到来自: {url}")
            threading.Thread(target=self._process_recieved_data, args=(text, url, title)).start()
            
            return 'OK', 200
    
    def _process_recieved_data(self, text, url, title):
        domain_regex = r"^(?:https?:)?(?:\/\/)?([^\/\?:]+)(?:[\/\?:].*)?$"
        domain = re.search(domain_regex, url).group(1)
        try:
            match domain:
                case "music.163.com":
                    song_id = re.search(r"id=(\d+)", url).group(1)
                    song_info = get_netease_music_details_text(song_id)
                    self.mainwindow.manual_extra_data.append({"description": "网易云音乐: " + title, "content": {"type": "text", "text": f"```经过清洗的网易云音乐网页: {title}\n{song_info}\n```"}})
                    if hasattr(self.mainwindow, 'add_listbox'):
                        self.mainwindow.add_window.after(0, self.mainwindow.add_listbox.insert, tk.END, "网易云音乐: " + title)
                case "b23.tv" | "bilibili.com" | "www.bilibili.com":
                    video_data = get_bili_text(url)
                    video_info = f'''标题: {video_data["title"]}\n简介: {video_data["desc"]}\n标签: {video_data["tag"]}\n字幕: \n{video_data["text"]}'''
                    self.mainwindow.manual_extra_data.append({"description": "哔哩哔哩视频: " + title, "content": {"type": "text", "text": f"```经过清洗的哔哩哔哩网页: {title}\n{video_info}\n```"}})
                    if hasattr(self.mainwindow, 'add_listbox'):
                        self.mainwindow.add_window.after(0, self.mainwindow.add_listbox.insert, tk.END, "哔哩哔哩视频: " + title)
                case _:
                    self.mainwindow.manual_extra_data.append({"description": "网页: " + title, "content": {"type": "text", "text": f"```网页: {title}\n{text}\n```"}})
                    if hasattr(self.mainwindow, 'add_listbox'):
                        self.mainwindow.add_window.after(0, self.mainwindow.add_listbox.insert, tk.END, "网页: " + title)
        except:
            self.mainwindow.manual_extra_data.append({"description": "网页: " + title, "content": {"type": "text", "text": f"```网页: {title}\n{text}\n```"}})
            if hasattr(self.mainwindow, 'add_listbox'):
                self.mainwindow.add_listbox.insert(tk.END, "网页: " + title)
    
    def run_server(self):
        self.server = make_server('localhost', 24981, self.app)
        self.server_thread = threading.Thread(target=self.server.serve_forever)
        self.server_thread.daemon = True
        self.server_thread.start()

class LRUCache:
    def __init__(self, capacity=50, allow_reverse=False):
        self.capacity = capacity
        self.cache = OrderedDict()
        self.allow_reverse = allow_reverse
        # 只有开启反向查询时才初始化字典，节省空间
        self.rev_cache = {} if allow_reverse else None
    
    def get(self, key):
        if key not in self.cache:
            return None
        
        # 移动到最新位置 (MRU)
        self.cache.move_to_end(key)
        val = self.cache[key]
        
        # 如果支持反向查询，既然这个key刚被访问过，它就是这个值对应的“最新”键
        if self.allow_reverse:
            self.rev_cache[val] = key
            
        return val
    
    def put(self, key, value):
        if key in self.cache:
            # key 已存在：移动到最新位置
            self.cache.move_to_end(key)
            
            # 处理反向索引更新
            if self.allow_reverse:
                old_val = self.cache[key]
                # 如果值发生了变化，且旧值的反向索引指向当前key，则删除旧索引
                if old_val != value and self.rev_cache.get(old_val) == key:
                    del self.rev_cache[old_val]
        else:
            # key 不存在：检查容量
            if len(self.cache) >= self.capacity:
                # 弹出最旧项 (FIFO)
                old_k, old_v = self.cache.popitem(last=False)
                
                # 如果被删除的键是其值的反向索引代表，则清理反向索引
                # 注意：如果 rev_cache[old_v] 指向的是别的（更新的）key，则不删除
                if self.allow_reverse and self.rev_cache.get(old_v) == old_k:
                    del self.rev_cache[old_v]
        
        # 更新主缓存
        self.cache[key] = value
        
        # 更新反向索引：无论 value 是否重复，当前 key 都是该 value 的“最新”代表
        if self.allow_reverse:
            self.rev_cache[value] = key
            
    def find_key(self, value):
        """
        通过值反向查询键。
        如果多个键对应同一个值，返回最新的（最后被 put 或 get 的）那个键。
        """
        if not self.allow_reverse:
            return None
        return self.rev_cache.get(value)

if __name__ == "__main__":
    mainwindow = MainWindow()
    trayicon = TrayIcon()
    trayicon.set_menu_shortcut(mainwindow.is_feature_web_server_enable)
    tray_thread = threading.Thread(target=trayicon.run)
    tray_thread.daemon = True  # 守护线程，主程序退出时自动退出
    tray_thread.start()
    mainwindow()