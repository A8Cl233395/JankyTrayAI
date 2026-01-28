import win32gui
import win32ui
import requests
from openai import OpenAI
from io import BytesIO
import base64
import pygetwindow as gw
from ctypes import windll
from PIL import Image, ImageGrab
from collections import OrderedDict
from flask import Flask, request, jsonify, send_from_directory, Response, make_response
from flask_cors import CORS
from werkzeug.serving import make_server
import os
import time
import chardet
import tkinter as tk
from tkinter import scrolledtext, ttk
import threading
from pystray import Icon, MenuItem, Menu
import json
import win32clipboard
import win32con
from hashlib import md5
from tkinterdnd2 import DND_FILES, TkinterDnD
import re
import sqlite3
import multiprocessing
from queue import Queue

oclients = {}

if os.path.exists('saves/models.json'):
    with open('saves/models.json', 'r', encoding='utf-8') as f:
        models = json.load(f)
    del f
else:
    raise FileNotFoundError("saves/models.json not found")


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
    if models[model]["url"] not in oclients:
        oclients[models[model]["url"]] = OpenAI(
            base_url=models[model]["url"],
            api_key=models[model]["api_key"],
        )
    return oclients[models[model]["url"]]

def get_bili_text(user_input):
    if user_input.startswith("BV") or user_input.startswith("av") or user_input.startswith("bv"):
        url = f"https://www.bilibili.com/video/{user_input}/"
    else:
        url = user_input
    header = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0"
    }
    html = requests.get(url, headers=header).text
    pat = r'''window.__INITIAL_STATE__=({.*?});'''
    res = re.findall(pat, html, re.DOTALL)
    data = json.loads(res[0])
    title = data["videoData"]["title"]
    bv = data["videoData"]["bvid"]
    tag = ' '.join(data["rcmdTabNames"])
    desc = data["videoData"]["desc"]
    pat = r'''window.__playinfo__=({.*?})</script>'''
    res = re.findall(pat, html, re.DOTALL)
    data = json.loads(res[0])
    for i in range(4):
        if i == 3:
            raise Exception("未找到合适的音频流。")
        try:
            headers = {"referer": f'https://www.bilibili.com/video/{bv}/', "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36 Edg/127.0.0.0"}
            audio_url = data["data"]["dash"]["audio"][i]["baseUrl"]
            audio_data = requests.get(audio_url, headers=headers)
            if audio_data.status_code == 200 or audio_data.status_code == 206:
                audio_data = audio_data.content
                break
        except:
            pass
    text = audio_transcription_azure(audio_data)
    return {'title': title, 'desc': desc, 'text': text, 'tag': tag}

def audio_transcription_azure(audio_data: bytes) -> str:
    response = requests.post(
        url=models["azure-speech-to-text"]["url"],
        headers={
            "Ocp-Apim-Subscription-Key": models["azure-speech-to-text"]["Ocp-Apim-Subscription-Key"]
        },
        files={'audio': ('test.mp3', audio_data, 'audio/mpeg')},
        data={'definition': '{"locales":["zh-CN", "en-US", "ja-JP"]}'}
    ).json()
    text = ""
    for i in response["phrases"]:
        text += i["text"] + "\n"
    return text

def get_netease_music_details_text(song_id, comment_limit=5):
    lyric_api = f"https://music.163.com/api/song/lyric?os=pc&id={song_id}&lv=-1&tv=-1"
    comment_api = f"https://music.163.com/api/v1/resource/comments/R_SO_4_{song_id}?offset=0&limit=3"
    details_api = f"https://music.163.com/api/song/detail/?ids=[{song_id}]"
    combined = ""

    lyric_json = requests.get(lyric_api).json()
    translations = {}
    time_tag_regex = r'\[(?:\d{2,}:)?\d{2}[:.]\d{2,}(?:\.\d+)?\]'
    if "tlyric" in lyric_json and lyric_json["tlyric"]["version"] and lyric_json["tlyric"]["lyric"]:
        for line in lyric_json["tlyric"]["lyric"].split("\n"):
            time_tag = re.match(time_tag_regex, line)
            if time_tag:
                cleaned_line = re.sub(time_tag_regex, '', line).strip()
                translations[time_tag.group()] = cleaned_line
    combined_lyrics = []
    for line in lyric_json["lrc"]["lyric"].split("\n"):
        time_tag = re.match(time_tag_regex, line)
        if time_tag:
            cleaned_line = re.sub(time_tag_regex, '', line).strip()
            combined_lyrics.append(cleaned_line)
            if time_tag.group() in translations:
                combined_lyrics.append(translations[time_tag.group()])
    combined_lyrics_text = "\n".join(combined_lyrics).strip()

    detail_json = requests.get(details_api).json()
    song_detail_json = detail_json["songs"][0]
    name = song_detail_json["name"]
    artists = [artist["name"] for artist in song_detail_json["artists"]]
    transname = song_detail_json["transName"] if "transName" in song_detail_json else None
    alias = song_detail_json["alias"][0] if "alias" in song_detail_json and song_detail_json["alias"] else None

    comment_json = requests.get(comment_api).json()
    hot_comments = comment_json["hotComments"]
    comments = [comment["content"] for comment in hot_comments][:comment_limit]
    comments_text = "\n\n".join(comments).strip()
    combined += f"曲名: {name}\n"
    combined += f"翻译名: {transname}\n" if transname else ""
    combined += f"别名: {alias}\n" if alias else ""
    combined += f"歌手: {', '.join(artists)}\n"
    combined += f"歌词:\n```\n{combined_lyrics_text}\n```\n"
    combined += f"热评:\n```\n{comments_text}\n```"
    return combined

class ChatInstance:
    def __init__(self, model = "deepseek-chat", vision_model = "qwen3-vl-plus-2025-12-19", messages: list[dict] | None = None, mainwindow = None):
        self.oclient = get_oclient(model)
        self.model = model
        self.vision_model = vision_model
        self.messages: list[dict] = messages if messages else []
        self.contain_image = False
        if self.messages:
            for message in self.messages:
                if message['role'] == 'user' and message['content'][0]['type'] == 'image_url':
                    self.contain_image = True
                    self.model = self.vision_model
                    self.oclient = get_oclient(self.model)
                    break
        if mainwindow:
            self.mainwindow = mainwindow
            self.function = self._direct_mode
        else:
            self.function = self._yield_mode

    def ai(self):
        completion = self.oclient.chat.completions.create(
            model=self.model,
            messages=self.messages,
            temperature=1,
            stream=True
        )
        return completion
    
    def __call__(self):
        return self.function()
    
    def _direct_mode(self):
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
                self.mainwindow.insert_message(delta.reasoning_content, tag="thinking")
            elif hasattr(delta, "content") and delta.content:
                if is_thinking and not is_answering:
                    is_answering = True
                    self.mainwindow.insert_message("\n---Answering---\n", tag="answering")
                full_content += delta.content
                self.mainwindow.insert_message(delta.content)
        self.messages.append({"role": "assistant", "content": full_content})

    def _yield_mode(self):
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
                    yield {"signal": 1}
                yield {"data": delta.reasoning_content}
            elif hasattr(delta, "content") and delta.content:
                if is_thinking and not is_answering:
                    is_answering = True
                    yield {"signal": 0}
                full_content += delta.content
                yield {"data": delta.content}
        self.messages.append({"role": "assistant", "content": full_content})

    def new(self):
        self.messages.append({"role": "user", "content": []})
    
    def add(self, content: dict):
        self.messages[-1]["content"].append(content)
        if not self.contain_image and content["type"] == "image_url":
            self.contain_image = True
            self.model = self.vision_model
            self.oclient = get_oclient(self.model)
    
    def merge(self):
        """合并连续的文本消息"""
        text_messages = []
        image_messages = []
        for message in self.messages[-1]["content"]:
            if message["type"] == "text":
                text_messages.append(message)
            else:
                image_messages.append(message)
        self.messages[-1]["content"] = image_messages + [{"type": "text", "text": "\n".join([i["text"] for i in text_messages])}]
    
    def set(self, content: list[dict]):
        self.messages[-1]["content"] = content
        if not self.contain_image and content[0]["type"] == "image_url":
            self.contain_image = True
            self.model = self.vision_model
            self.oclient = get_oclient(self.model)
