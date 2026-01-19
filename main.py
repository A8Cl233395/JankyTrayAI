import base64
from ctypes import windll
import os
import time
from io import BytesIO
import chardet
from openai import OpenAI
import tkinter as tk
from tkinter import scrolledtext, ttk
import threading
from pystray import Icon, MenuItem, Menu
from PIL import Image, ImageGrab
import json
import pygetwindow as gw
import win32gui
import win32ui
import requests
import win32clipboard
import win32con
from hashlib import md5
from tkinterdnd2 import DND_FILES, TkinterDnD
import re

oclients = {}

if os.path.exists('models.json'):
    with open('models.json', 'r', encoding='utf-8') as f:
        models = json.load(f)
    del f
else:
    raise FileNotFoundError("models.json not found")

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

        self.histories = []
        if os.path.exists('histories.json'):
            with open('histories.json', 'r', encoding='utf-8') as f:
                self.histories = json.load(f)
            del f
        
        self.last_active_window = None
        self.manual_extra_data = []

        self.last_clipboard_data = []
        self.current_chat_index = -1

        self.is_feature_auto_vision_mode = True
        self.is_feature_screenshot_enable = False
        self.is_feature_clipboard_enable = False
        self.main_model = "deepseek-chat"
        self.assist_model = "qwen-flash"
        self.vision_model = "qwen3-vl-plus-2025-12-19"

        if os.path.exists('settings.json'):
            with open('settings.json', 'r', encoding='utf-8') as f:
                settings = json.load(f)
            del f
            self.is_feature_auto_vision_mode = settings["is_feature_auto_vision_mode"]
            self.is_feature_screenshot_enable = settings["is_feature_screenshot_enable"]
            self.is_feature_clipboard_enable = settings["is_feature_clipboard_enable"]
            self.main_model = settings["main_model"]
            self.assist_model = settings["assist_model"]
            self.vision_model = settings["vision_model"]
        
        self.is_vision_mode = False
        
        if self.is_feature_screenshot_enable:
            self.get_active_window_thread = threading.Thread(target=self._get_active_window_loop)
            self.get_active_window_thread.daemon = True
            self.get_active_window_thread.start()
        
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
            self.display_area.see(tk.END)  # 滚动到最新消息
            if not hasattr(self, 'chatinstance'):
                self.new_chat()
                threading.Thread(target=self._generate_chat_title, args=(user_input,)).start()
            self.generate_response_thread = threading.Thread(target=self._generate_and_insert_response, args=(user_input,))
            self.generate_response_thread.start()

    def _generate_and_insert_response(self, user_input: str):
        self.chatinstance.new()
        self.auto_add_extra_data()
        if self.is_vision_mode:
            if self.chatinstance.model != self.vision_model:
                self.chatinstance.model = self.vision_model
                self.chatinstance.oclient = get_oclient(self.vision_model)
        self.chatinstance.add({"type": "text", "text": user_input})
        self.chatinstance.merge()
        self.insert_message(f"AI: ", "assistant")
        self.chatinstance()
        self.insert_message("\n")
        self.display_area.see(tk.END)  # 滚动到最新消息

    def _generate_chat_title(self, user_input: str):
        title = ask_ai("你是一个专业的对话标题生成器，你需要根据用户的输入生成一句对话标题。", user_input, model=self.assist_model, prefix="```标题\n", stop="\n```")
        self.histories[0]["title"] = title
        if hasattr(self, 'history_listbox'):
            self.history_listbox.delete(0)
            self.history_listbox.insert(0, self.histories[0]["title"])
    
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
        self.checkbox_screenshot.pack(pady=10)

        is_feature_clipboard_enable = tk.BooleanVar(value=self.is_feature_clipboard_enable)
        self.checkbox_clipboard = ttk.Checkbutton(self.settings_root, text="自动添加剪贴板内容", variable=is_feature_clipboard_enable, command=lambda: self._set_feature_clipboard(is_feature_clipboard_enable.get()))
        self.checkbox_clipboard.pack(pady=10)

        is_feature_auto_vision_mode_enable = tk.BooleanVar(value=self.is_feature_auto_vision_mode)
        self.checkbox_vision_mode = ttk.Checkbutton(self.settings_root, text="自动视觉模式", variable=is_feature_auto_vision_mode_enable, command=lambda: self._set_feature_auto_vision_mode(is_feature_auto_vision_mode_enable.get()))
        self.checkbox_vision_mode.pack(pady=10)

        self.entry_main_model = ttk.Entry(self.settings_root, font=('微软雅黑', 10), width=20)
        self.entry_main_model.pack(pady=10)
        self.entry_main_model.insert(0, self.main_model)
        self.entry_main_model.bind('<Return>', lambda event: self._set_main_model(self.entry_main_model.get()))

        self.entry_vision_model = ttk.Entry(self.settings_root, font=('微软雅黑', 10), width=20)
        self.entry_vision_model.pack(pady=10)
        self.entry_vision_model.insert(0, self.vision_model)
        self.entry_vision_model.bind('<Return>', lambda event: self._set_vision_model(self.entry_vision_model.get()))

        self.entry_assist_model = ttk.Entry(self.settings_root, font=('微软雅黑', 10), width=20)
        self.entry_assist_model.pack(pady=10)
        self.entry_assist_model.insert(0, self.assist_model)
        self.entry_assist_model.bind('<Return>', lambda event: self._set_assist_model(self.entry_assist_model.get()))
    
    def _set_feature_screenshot(self, enable: bool):
        self.is_feature_screenshot_enable = enable
        if enable:
            if not hasattr(self, 'get_active_window_thread') or not self.get_active_window_thread.is_alive():
                self.get_active_window_thread = threading.Thread(target=self._get_active_window_loop)
                self.get_active_window_thread.daemon = True  # 守护线程，主程序退出时自动退出
                self.get_active_window_thread.start()
    
    def _set_feature_clipboard(self, enable: bool):
        self.is_feature_clipboard_enable = enable
    
    def _set_feature_auto_vision_mode(self, enable: bool):
        self.is_feature_auto_vision_mode = enable
    
    def _set_main_model(self, model: str):
        self.main_model = model
    
    def _set_vision_model(self, model: str):
        self.vision_model = model
    
    def _set_assist_model(self, model: str):
        self.assist_model = model
    
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
            yscrollcommand=self.history_scrollbar.set,
            font=("微软雅黑", 10),
            selectmode=tk.SINGLE  # 只能单选
        )
        self.history_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.history_scrollbar.config(command=self.history_listbox.yview)
        # 绑定选择事件
        self.history_listbox.bind('<<ListboxSelect>>', self._on_history_select)
        for i in self.histories:
            self.history_listbox.insert(tk.END, i["title"])
    
    def _on_history_select(self, event):
        """列表项被选中时的回调函数"""
        # 获取当前选中的索引
        selection = self.history_listbox.curselection()
        if selection:
            index = selection[0]
            self.load_history(index)
    
    def _remove_history(self, event):
        """删除选中的历史记录"""
        selection = self.history_listbox.curselection()
        if selection:
            index = selection[0]
            self.history_listbox.delete(index)
            del self.histories[index]
            self.current_chat_index = max(0, self.current_chat_index - 1)
            self.load_history(self.current_chat_index)

    def load_history(self, index: int):
        if index == self.current_chat_index:
            self.display_area.see(tk.END)  # 滚动到最新消息
            return
        if hasattr(self, 'generate_response_thread') and self.generate_response_thread.is_alive():
            self.display_area.see(tk.END)  # 滚动到最新消息
            return
        if hasattr(self, 'chatinstance'):
            self.archive_chat()
        self.current_chat_index = index
        messages = self.histories[index]["messages"]
        self.chatinstance = ChatInstance(self.main_model, messages, mainwindow=self)
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
        
        for message in messages:
            if message["role"] == "user":
                if message["content"][0]["type"] == "image_url":
                    self.is_vision_mode = True
                    break
        else:
            self.is_vision_mode = False
    
    def toggle_show(self):
        if self.root.state() == 'normal':
            self.root.withdraw()
        else:
            self.root.deiconify()
    
    def new_chat(self):
        self.chatinstance = ChatInstance(self.main_model, mainwindow=self)
        self.current_chat_index = 0
        for i in self.manual_extra_data:
            if i["type"] == "image_url":
                self.is_vision_mode = True
                break
        else:
            self.is_vision_mode = False
        self.histories.insert(0, {"title": "新对话", "messages": None})
        if hasattr(self, 'history_listbox') and self.history_listbox.winfo_exists():
            self.history_listbox.insert(0, self.histories[0]["title"])
    
    def archive_chat(self):
        if hasattr(self, "chatinstance"):
            messages = self.chatinstance.messages
            self.histories[self.current_chat_index]["messages"] = messages
            del self.chatinstance

    def on_newchat(self):
        self.archive_chat()
        self.display_area.delete(1.0, tk.END)
    
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
                    self.manual_extra_data.append({"type": "text", "text": f"```无法读取的文件\n{file_path}\n```"})
                    self.add_listbox.insert(tk.END, "文件: " + file_path.split("/")[-1][:30])
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
                    self.manual_extra_data.append({"type": "text", "text": f"```文件: {filename}\n{text}\n```"})
                    self.add_listbox.insert(tk.END, "文件: " + filename[:30])
                else:
                    self.manual_extra_data.append({"type": "text", "text": f"```无法读取的文件\n{file_path}\n```"})
                    self.add_listbox.insert(tk.END, "文件: " + file_path.split("/")[-1][:30])
    
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
                self.manual_extra_data.append({"type": "text", "text": f"```文本\n{text}\n```"})
                self.add_listbox.insert(tk.END, "文本: " + text[:30])
            elif win32clipboard.IsClipboardFormatAvailable(win32con.CF_DIB):
                image = ImageGrab.grabclipboard()
                if image is not None:
                    if not self.is_feature_auto_vision_mode:
                        text = ocr_image_azure(image)
                        self.manual_extra_data.append({"type": "text", "text": f"```图片上的文本\n{text}\n```"})
                        self.add_listbox.insert(tk.END, "图片: " + text[:30].replace("\n", " "))
                    else:
                        self.is_vision_mode = True
                        self.manual_extra_data.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_to_b64(image)}"}})
                        self.add_listbox.insert(tk.END, "图片")
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
                    if not self.is_feature_auto_vision_mode:
                        text = ocr_image_azure(image)
                        self.chatinstance.add({"type": "text", "text": f"```自动插入: 最后一个窗口上的文本\n{text}\n```"})
                    else:
                        self.is_vision_mode = True
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
                            if not self.is_feature_auto_vision_mode:
                                text = ocr_image_azure(image)
                                self.chatinstance.add({"type": "text", "text": f"```自动插入: 剪贴板中图片上的文本\n{text}\n```"})
                            else:
                                self.is_vision_mode = True
                                self.chatinstance.add({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_to_b64(image)}"}})
            except Exception as e:
                print(e)
            finally:
                try:
                    win32clipboard.CloseClipboard()
                except:
                    pass
        self.last_clipboard_data = current_clipboard_data

        if hasattr(self, 'add_window'): # 处理手动添加的内容
            self.chatinstance.messages[-1]["content"].extend(self.manual_extra_data)
            self.add_listbox.delete(0, tk.END)
            self.manual_extra_data = []
        if self.chatinstance.messages[-1]["content"]:
            self.chatinstance.add({"type": "text", "text": "额外内容结束\n---"})

    def _get_active_window_loop(self):
        while self.is_feature_screenshot_enable:
            active_window = gw.getActiveWindow()
            if active_window and active_window.title not in ["设置", "添加多媒体", "历史记录", "托盘小工具", ""]:
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
            self.archive_chat()
        with open("histories.json", "w", encoding="utf-8") as f:
            json.dump(self.histories, f, ensure_ascii=False, indent=4)
        with open("settings.json", "w", encoding="utf-8") as f:
            settings = {
                "is_feature_screenshot_enable": self.is_feature_screenshot_enable,
                "is_feature_clipboard_enable": self.is_feature_clipboard_enable,
                "is_feature_auto_vision_mode": self.is_feature_auto_vision_mode,
                "main_model": self.main_model,
                "assist_model": self.assist_model,
                "vision_model": self.vision_model,
            }
            json.dump(settings, f, ensure_ascii=False, indent=4)
        self.root.after(10, self.root.quit) # 退出 Tkinter

class TrayIcon:
    def __init__(self, mainwindow: MainWindow):
        self.mainwindow = mainwindow
        image = Image.open("icon.png")  # 使用外部图标文件
        self.icon = Icon("mini_app", image, menu=Menu(
            MenuItem("显示", self.mainwindow.toggle_show, default=True, visible=False),
            MenuItem("新对话", self.mainwindow.on_newchat),
            MenuItem("添加...", self.mainwindow.open_add_multimedia),
            MenuItem("历史记录", self.mainwindow.open_history),
            MenuItem("设置", self.mainwindow.open_settings),
            MenuItem("退出", self.on_exit)
        ))
    
    def on_exit(self):
        """退出程序"""
        self.icon.stop()   # 停止托盘
        self.mainwindow.on_quit()
    
    def run(self):
        self.icon.run()

class ChatInstance:
    def __init__(self, model, messages: list[dict] | None = None, mainwindow: MainWindow = None):
        self.oclient = get_oclient(model)
        self.model = model
        self.messages: list[dict] = messages if messages else []
        self.mainwindow = mainwindow

    def ai(self):
        completion = self.oclient.chat.completions.create(
            model=self.model,
            messages=self.messages,
            temperature=1,
            stream=True
        )
        return completion
    
    def __call__(self):
        completion = self.ai()
        full_content = ""
        is_thinking = False
        is_answering = False
        self.tool_calls = []
        for chunk in completion:
            delta = chunk.choices[0].delta
            if hasattr(delta, "reasoning_content") and delta.reasoning_content:
                if not is_thinking:
                    is_thinking = True
                    self.mainwindow.insert_message("\n---Thinking---\n", tag="thinking")
                self.mainwindow.insert_message(delta.reasoning_content)
            elif hasattr(delta, "content") and delta.content:
                if is_thinking and not is_answering:
                    is_answering = True
                    self.mainwindow.insert_message("\n---Answering---\n", tag="answering")
                full_content += delta.content
                self.mainwindow.insert_message(delta.content)
        self.messages.append({"role": "assistant", "content": full_content})

    def new(self):
        self.messages.append({"role": "user", "content": []})
    
    def add(self, content: dict):
        self.messages[-1]["content"].append(content)
    
    def merge(self):
        """合并连续的文本消息"""
        text_messages = []
        image_messages = []
        for messages in self.messages[-1]["content"]:
            if messages["type"] == "text":
                text_messages.append(messages)
            else:
                image_messages.append(messages)
        self.messages[-1]["content"] = image_messages + [{"type": "text", "text": "\n".join([i["text"] for i in text_messages])}]

def ask_ai(system: str, user: str, model: str = "deepseek-chat", prefix: str = "", stop: str = ""):
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    if prefix:
        messages.append({"role": "assistant", "content": prefix, "prefix": True})
    params = {
        "model": model,
        "messages": messages,
        "temperature": 0,
        "stream": False,
    }
    if stop:
        params["stop"] = stop
    response = get_oclient(model).chat.completions.create(**params)
    return response.choices[0].message.content

def capture_window_no_border(window: gw.Window) -> Image.Image | None:
    def capture_window(window):
        hwnd = window._hWnd
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        width = right - left
        height = bottom - top
        hwndDC = win32gui.GetWindowDC(hwnd)
        mfcDC = win32ui.CreateDCFromHandle(hwndDC)
        saveDC = mfcDC.CreateCompatibleDC()
        saveBitMap = win32ui.CreateBitmap()
        saveBitMap.CreateCompatibleBitmap(mfcDC, width, height)
        saveDC.SelectObject(saveBitMap)
        result = windll.user32.PrintWindow(hwnd, saveDC.GetSafeHdc(), 0x00000002)
        if result != 1:
            result = windll.user32.PrintWindow(hwnd, saveDC.GetSafeHdc(), 0)
            if result != 1:
                return None
        bmp_info = saveBitMap.GetInfo()
        bmp_str = saveBitMap.GetBitmapBits(True)
        im = Image.frombuffer(
            'RGBA', (bmp_info['bmWidth'], bmp_info['bmHeight']), bmp_str, 'raw', 'BGRA', 0, 1
        )
        im = im.convert('RGB')
        win32gui.DeleteObject(saveBitMap.GetHandle())
        saveDC.DeleteDC()
        mfcDC.DeleteDC()
        win32gui.ReleaseDC(hwnd, hwndDC)
        return im

    def crop_black_borders(image):
        if image.mode != 'RGB':
            image = image.convert('RGB')
        width, height = image.size
        if width == 0 or height == 0:
            return image
        pixels = image.load()
        top = 0
        for y in range(height):
            for x in range(width):
                if pixels[x, y] != (0, 0, 0):
                    top = y
                    break
            else:
                continue
            break
        bottom = height - 1
        for y in range(height - 1, -1, -1):
            for x in range(width):
                if pixels[x, y] != (0, 0, 0):
                    bottom = y
                    break
            else:
                continue
            break
        left = 0
        for x in range(width):
            for y in range(height):
                if pixels[x, y] != (0, 0, 0):
                    left = x
                    break
            else:
                continue
            break
        right = width - 1
        for x in range(width - 1, -1, -1):
            for y in range(height):
                if pixels[x, y] != (0, 0, 0):
                    right = x
                    break
            else:
                continue
            break
        if left >= right or top >= bottom:
            return image
        cropped_image = image.crop((left, top, right + 1, bottom + 1))
        return cropped_image
    return crop_black_borders(capture_window(window))

def ocr_image_azure(image: Image.Image) -> str:
    # 将 PIL Image 转换为 PNG 字节流
    if models["azure-computer-vision"]["url"] == "xxx":
        raise Exception("请配置 Azure Computer Vision 的 URL 和 Ocp-Apim-Subscription-Key。如果没有，保持自动视觉模式开启。")
    
    img_byte_arr = BytesIO()
    image.save(img_byte_arr, format='PNG')
    img_byte_arr = img_byte_arr.getvalue()
    
    data = requests.post(
        url=models["azure-computer-vision"]["url"],
        headers={
            "Ocp-Apim-Subscription-Key": models["azure-computer-vision"]["Ocp-Apim-Subscription-Key"],
            "Content-Type": "application/octet-stream",
        },
        params={
            "features": "read"
        },
        data=img_byte_arr
    ).json()
    if "error" in data:
        raise Exception(data["error"]["message"])
    lines = data["readResult"]["blocks"][0]
    text = ""
    for line in lines['lines']:
        text += line['text'] + "\n"
    return text

def image_to_b64(image: Image.Image) -> str:
    if image.mode != 'RGB':
        image = image.convert('RGB')
    img_byte_arr = BytesIO()
    image.save(img_byte_arr, format='JPEG', quality=80)
    img_byte_arr = img_byte_arr.getvalue()
    return base64.b64encode(img_byte_arr).decode('utf-8')

def get_oclient(model) -> OpenAI:
    if model not in oclients:
        oclients[model] = OpenAI(
            base_url=models[model]["url"],
            api_key=models[model]["api_key"],
        )
    return oclients[model]

    
def run():
    mainwindow = MainWindow()
    trayicon = TrayIcon(mainwindow)
    tray_thread = threading.Thread(target=trayicon.run)
    tray_thread.daemon = True  # 守护线程，主程序退出时自动退出
    tray_thread.start()
    mainwindow()

if __name__ == "__main__":
    run()