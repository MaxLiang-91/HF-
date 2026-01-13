#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HuggingFace 下载工具
支持断点续传、自定义保存路径
"""

import os
import sys
import requests
import threading
import time
from pathlib import Path
from urllib.parse import urlparse, unquote, urljoin
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import re
import json
from bs4 import BeautifulSoup


class HFDownloader:
    """HuggingFace 文件下载器，支持断点续传"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        self.cancel_flag = False
        self.pause_flag = False
        
    def parse_hf_url(self, url):
        """
        解析 HuggingFace URL，提取模型信息和文件路径
        支持多种URL格式，包括目录URL
        返回: (download_url, filename, is_directory, repo_info)
        """
        # 移除查询参数
        url = url.split('?')[0]
        
        # 检查是否是目录URL (tree格式)
        tree_patterns = [
            r'hf-mirror\.com/([^/]+)/([^/]+)/tree/([^/]+)(?:/(.*))?',
            r'huggingface\.co/([^/]+)/([^/]+)/tree/([^/]+)(?:/(.*))?',
        ]
        
        for pattern in tree_patterns:
            match = re.search(pattern, url)
            if match:
                username, model, branch = match.groups()[:3]
                subpath = match.groups()[3] if len(match.groups()) > 3 else ''
                repo_info = {
                    'username': username,
                    'model': model,
                    'branch': branch,
                    'subpath': subpath or ''
                }
                return None, None, True, repo_info
        
        # 检查单文件URL
        file_patterns = [
            # https://hf-mirror.com/username/model/resolve/main/file.bin
            r'hf-mirror\.com/([^/]+)/([^/]+)/resolve/([^/]+)/(.+)',
            # https://hf-mirror.com/username/model/blob/main/file.bin
            r'hf-mirror\.com/([^/]+)/([^/]+)/blob/([^/]+)/(.+)',
            # https://huggingface.co/username/model/resolve/main/file.bin
            r'huggingface\.co/([^/]+)/([^/]+)/resolve/([^/]+)/(.+)',
            # https://huggingface.co/username/model/blob/main/file.bin
            r'huggingface\.co/([^/]+)/([^/]+)/blob/([^/]+)/(.+)',
        ]
        
        for pattern in file_patterns:
            match = re.search(pattern, url)
            if match:
                username, model, branch, filepath = match.groups()
                # 将 blob 转换为 resolve 用于下载
                download_url = f"https://hf-mirror.com/{username}/{model}/resolve/{branch}/{filepath}"
                filename = os.path.basename(unquote(filepath))
                return download_url, filename, False, None
        
        # 如果是直接的文件URL
        if url.startswith('http'):
            filename = os.path.basename(unquote(urlparse(url).path))
            if not filename:
                filename = 'downloaded_file'
            return url, filename, False, None
            
        return None, None, False, None
    
    def get_file_size(self, url):
        """获取远程文件大小"""
        try:
            response = self.session.head(url, allow_redirects=True, timeout=10)
            if response.status_code == 200:
                return int(response.headers.get('Content-Length', 0))
        except Exception as e:
            print(f"获取文件大小失败: {e}")
        return 0
    
    def format_size(self, size):
        """格式化文件大小"""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024.0:
                return f"{size:.2f} {unit}"
            size /= 1024.0
        return f"{size:.2f} PB"
    
    def format_speed(self, speed):
        """格式化下载速度"""
        return f"{self.format_size(speed)}/s"
    
    def download_file(self, url, save_path, progress_callback=None, status_callback=None):
        """
        下载文件，支持断点续传
        
        Args:
            url: 下载链接
            save_path: 保存路径
            progress_callback: 进度回调函数 (downloaded, total, speed, percentage)
            status_callback: 状态回调函数 (message)
        """
        self.cancel_flag = False
        self.pause_flag = False
        
        # 确保目录存在
        os.makedirs(os.path.dirname(save_path) if os.path.dirname(save_path) else '.', exist_ok=True)
        
        # 检查已下载的文件大小
        downloaded_size = 0
        if os.path.exists(save_path):
            downloaded_size = os.path.getsize(save_path)
        
        # 获取文件总大小
        total_size = self.get_file_size(url)
        
        if total_size == 0:
            if status_callback:
                status_callback("无法获取文件大小，尝试直接下载...")
        
        # 如果文件已完整下载
        if downloaded_size > 0 and downloaded_size == total_size:
            if status_callback:
                status_callback("文件已存在且完整，无需重新下载")
            if progress_callback:
                progress_callback(total_size, total_size, 0, 100.0)
            return True
        
        # 设置断点续传的请求头
        headers = self.session.headers.copy()
        if downloaded_size > 0:
            headers['Range'] = f'bytes={downloaded_size}-'
            if status_callback:
                status_callback(f"从 {self.format_size(downloaded_size)} 处继续下载...")
        
        try:
            response = self.session.get(url, headers=headers, stream=True, timeout=30)
            
            # 检查是否支持断点续传
            if downloaded_size > 0 and response.status_code != 206:
                if status_callback:
                    status_callback("服务器不支持断点续传，从头开始下载...")
                downloaded_size = 0
                response = self.session.get(url, stream=True, timeout=30)
            
            if response.status_code not in [200, 206]:
                if status_callback:
                    status_callback(f"下载失败: HTTP {response.status_code}")
                return False
            
            # 打开文件（追加或新建）
            mode = 'ab' if downloaded_size > 0 else 'wb'
            
            # 下载参数
            chunk_size = 8192  # 8KB
            start_time = time.time()
            last_update_time = start_time
            last_downloaded = downloaded_size
            
            with open(save_path, mode) as f:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    # 检查暂停标志
                    while self.pause_flag and not self.cancel_flag:
                        time.sleep(0.1)
                    
                    # 检查取消标志
                    if self.cancel_flag:
                        if status_callback:
                            status_callback("下载已取消")
                        return False
                    
                    if chunk:
                        f.write(chunk)
                        downloaded_size += len(chunk)
                        
                        # 计算速度和进度
                        current_time = time.time()
                        if current_time - last_update_time >= 0.5:  # 每0.5秒更新一次
                            elapsed = current_time - last_update_time
                            speed = (downloaded_size - last_downloaded) / elapsed
                            percentage = (downloaded_size / total_size * 100) if total_size > 0 else 0
                            
                            if progress_callback:
                                progress_callback(downloaded_size, total_size, speed, percentage)
                            
                            last_update_time = current_time
                            last_downloaded = downloaded_size
            
            # 最终更新进度
            if progress_callback:
                progress_callback(downloaded_size, total_size, 0, 100.0)
            
            if status_callback:
                status_callback("下载完成！")
            
            return True
            
        except Exception as e:
            if status_callback:
                status_callback(f"下载出错: {str(e)}")
            return False
    
    def cancel_download(self):
        """取消下载"""
        self.cancel_flag = True
    
    def pause_download(self):
        """暂停下载"""
        self.pause_flag = True
    
    def resume_download(self):
        """恢复下载"""
        self.pause_flag = False
    
    def get_repo_files(self, username, model, branch='main', subpath=''):
        """
        获取HuggingFace仓库中的所有文件列表
        返回: [(relative_path, download_url, file_size), ...]
        """
        try:
            # 使用HuggingFace API获取文件列表
            api_url = f"https://hf-mirror.com/api/models/{username}/{model}/tree/{branch}"
            if subpath:
                api_url += f"/{subpath}"
            
            response = self.session.get(api_url, timeout=30)
            if response.status_code != 200:
                return None
            
            files_info = []
            data = response.json()
            
            for item in data:
                if item['type'] == 'file':
                    relative_path = item['path']
                    file_size = item.get('size', 0)
                    download_url = f"https://hf-mirror.com/{username}/{model}/resolve/{branch}/{relative_path}"
                    files_info.append((relative_path, download_url, file_size))
            
            return files_info
            
        except Exception as e:
            print(f"获取文件列表失败: {e}")
            return None


class DownloaderGUI:
    """下载器图形界面"""
    
    def __init__(self, root):
        self.root = root
        self.root.title("HuggingFace 下载工具")
        self.root.geometry("900x700")
        self.root.resizable(True, True)
        
        self.downloader = HFDownloader()
        self.download_thread = None
        self.is_downloading = False
        self.batch_mode = False  # 批量下载模式
        self.file_queue = []  # 文件下载队列
        self.current_file_index = 0  # 当前下载文件索引
        self.all_files = []  # 所有文件列表
        self.file_selection_window = None  # 文件选择窗口
        
        self.create_widgets()
        
    def create_widgets(self):
        """创建界面组件"""
        # 主框架
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(5, weight=1)
        
        # 下载模式选择
        mode_frame = ttk.LabelFrame(main_frame, text="下载模式", padding="5")
        mode_frame.grid(row=0, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)
        
        self.mode_var = tk.StringVar(value="single")
        ttk.Radiobutton(mode_frame, text="单文件下载", variable=self.mode_var, 
                       value="single", command=self.on_mode_change).pack(side=tk.LEFT, padx=10)
        ttk.Radiobutton(mode_frame, text="批量下载（整个模型/目录）", variable=self.mode_var, 
                       value="batch", command=self.on_mode_change).pack(side=tk.LEFT, padx=10)
        
        # URL输入
        ttk.Label(main_frame, text="下载地址:").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.url_entry = ttk.Entry(main_frame, width=70)
        self.url_entry.grid(row=1, column=1, sticky=(tk.W, tk.E), pady=5, padx=5)
        self.url_entry.insert(0, "https://hf-mirror.com/")
        
        # 提示标签
        self.hint_label = ttk.Label(main_frame, text="提示：粘贴单个文件的URL", foreground="gray")
        self.hint_label.grid(row=2, column=1, sticky=tk.W, padx=5)
        
        # 保存路径
        ttk.Label(main_frame, text="保存路径:").grid(row=3, column=0, sticky=tk.W, pady=5)
        path_frame = ttk.Frame(main_frame)
        path_frame.grid(row=3, column=1, sticky=(tk.W, tk.E), pady=5)
        path_frame.columnconfigure(0, weight=1)
        
        self.path_entry = ttk.Entry(path_frame)
        self.path_entry.grid(row=0, column=0, sticky=(tk.W, tk.E), padx=(0, 5))
        self.path_entry.insert(0, os.path.join(os.path.expanduser("~"), "Downloads"))
        
        ttk.Button(path_frame, text="浏览...", command=self.browse_path).grid(row=0, column=1)
        
        # 文件名（仅单文件模式显示）
        self.filename_label = ttk.Label(main_frame, text="文件名:")
        self.filename_label.grid(row=4, column=0, sticky=tk.W, pady=5)
        self.filename_entry = ttk.Entry(main_frame)
        self.filename_entry.grid(row=4, column=1, sticky=(tk.W, tk.E), pady=5, padx=5)
        
        # 按钮框架
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=5, column=0, columnspan=2, pady=10, sticky=tk.N)
        
        self.download_btn = ttk.Button(button_frame, text="开始下载", command=self.start_download)
        self.download_btn.grid(row=0, column=0, padx=5)
        
        self.pause_btn = ttk.Button(button_frame, text="暂停", command=self.pause_download, state=tk.DISABLED)
        self.pause_btn.grid(row=0, column=1, padx=5)
        
        self.cancel_btn = ttk.Button(button_frame, text="取消", command=self.cancel_download, state=tk.DISABLED)
        self.cancel_btn.grid(row=0, column=2, padx=5)
        
        # 进度框架
        progress_frame = ttk.LabelFrame(main_frame, text="下载进度", padding="10")
        progress_frame.grid(row=6, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S), pady=10)
        progress_frame.columnconfigure(0, weight=1)
        progress_frame.rowconfigure(3, weight=1)
        
        # 批量下载进度（整体）
        self.batch_progress_frame = ttk.Frame(progress_frame)
        self.batch_label = ttk.Label(self.batch_progress_frame, text="整体进度: 0/0 文件")
        self.batch_label.pack(anchor=tk.W, pady=2)
        
        # 当前文件进度
        self.progress_bar = ttk.Progressbar(progress_frame, mode='determinate', length=300)
        self.progress_bar.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=5)
        
        self.progress_label = ttk.Label(progress_frame, text="等待开始...")
        self.progress_label.grid(row=2, column=0, sticky=tk.W, pady=5)
        
        # 状态日志
        self.log_text = scrolledtext.ScrolledText(progress_frame, height=15, width=80)
        self.log_text.grid(row=3, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5)
        
    def browse_path(self):
        """浏览保存路径"""
        directory = filedialog.askdirectory(initialdir=self.path_entry.get())
        if directory:
            self.path_entry.delete(0, tk.END)
            self.path_entry.insert(0, directory)
    
    def on_mode_change(self):
        """切换下载模式"""
        mode = self.mode_var.get()
        if mode == "batch":
            self.batch_mode = True
            self.filename_label.grid_remove()
            self.filename_entry.grid_remove()
            self.hint_label.config(text="提示：粘贴模型主页URL（如 .../tree/main）")
            self.batch_progress_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=5)
        else:
            self.batch_mode = False
            self.filename_label.grid()
            self.filename_entry.grid()
            self.hint_label.config(text="提示：粘贴单个文件的URL")
            self.batch_progress_frame.grid_remove()
    
    def log_message(self, message):
        """添加日志消息"""
        timestamp = time.strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)
        self.root.update_idletasks()
    
    def update_progress(self, downloaded, total, speed, percentage):
        """更新进度"""
        self.progress_bar['value'] = percentage
        
        if total > 0:
            progress_text = f"{self.downloader.format_size(downloaded)} / {self.downloader.format_size(total)}"
            if speed > 0:
                progress_text += f" | 速度: {self.downloader.format_speed(speed)}"
            progress_text += f" | {percentage:.1f}%"
        else:
            progress_text = f"{self.downloader.format_size(downloaded)}"
            if speed > 0:
                progress_text += f" | 速度: {self.downloader.format_speed(speed)}"
        
        self.progress_label['text'] = progress_text
        self.root.update_idletasks()
    
    def update_status(self, message):
        """更新状态"""
        self.log_message(message)
    
    def start_download(self):
        """开始下载"""
        url = self.url_entry.get().strip()
        save_dir = self.path_entry.get().strip()
        
        if not url:
            messagebox.showwarning("警告", "请输入下载地址")
            return
        
        if not save_dir:
            messagebox.showwarning("警告", "请选择保存路径")
            return
        
        # 解析URL
        download_url, auto_filename, is_directory, repo_info = self.downloader.parse_hf_url(url)
        
        if is_directory and self.batch_mode:
            # 批量下载模式
            self.start_batch_download(repo_info, save_dir)
        elif not is_directory and not self.batch_mode:
            # 单文件下载模式
            self.start_single_download(download_url, auto_filename, save_dir)
        else:
            if is_directory:
                messagebox.showerror("错误", "检测到目录URL，请切换到「批量下载」模式")
            else:
                messagebox.showerror("错误", "检测到单文件URL，请切换到「单文件下载」模式")
    
    def start_single_download(self, download_url, auto_filename, save_dir):
        """开始单文件下载"""
        if not download_url:
            messagebox.showerror("错误", "无法解析下载地址，请检查URL格式")
            return
        
        # 获取文件名
        filename = self.filename_entry.get().strip()
        if not filename:
            filename = auto_filename
            self.filename_entry.insert(0, filename)
        
        save_path = os.path.join(save_dir, filename)
        
        self.log_message(f"准备下载: {self.url_entry.get()}")
        self.log_message(f"解析后URL: {download_url}")
        self.log_message(f"保存位置: {save_path}")
        
        # 更新按钮状态
        self.download_btn['state'] = tk.DISABLED
        self.pause_btn['state'] = tk.NORMAL
        self.cancel_btn['state'] = tk.NORMAL
        self.is_downloading = True
        
        # 在新线程中下载
        self.download_thread = threading.Thread(
            target=self._download_worker,
            args=(download_url, save_path),
            daemon=True
        )
        self.download_thread.start()
    
    def start_batch_download(self, repo_info, save_dir):
        """开始批量下载"""
        self.log_message(f"正在获取文件列表...")
        self.log_message(f"仓库: {repo_info['username']}/{repo_info['model']}")
        self.log_message(f"分支: {repo_info['branch']}")
        if repo_info['subpath']:
            self.log_message(f"子目录: {repo_info['subpath']}")
        
        # 在后台线程获取文件列表
        thread = threading.Thread(
            target=self._fetch_files_and_show_selection,
            args=(repo_info, save_dir),
            daemon=True
        )
        thread.start()
    
    def _fetch_files_and_show_selection(self, repo_info, save_dir):
        """获取文件列表并显示选择界面"""
        files = self.downloader.get_repo_files(
            repo_info['username'],
            repo_info['model'],
            repo_info['branch'],
            repo_info['subpath']
        )
        
        if not files:
            self.root.after(0, lambda: messagebox.showerror("错误", "无法获取文件列表，请检查URL是否正确"))
            return
        
        self.all_files = files
        total_size = sum(f[2] for f in files)
        self.root.after(0, lambda: self.log_message(f"找到 {len(files)} 个文件，总大小: {self.downloader.format_size(total_size)}"))
        
        # 显示文件选择窗口
        self.root.after(0, lambda: self._show_file_selection_window(files, save_dir))
    
    def _show_file_selection_window(self, files, save_dir):
        """显示文件选择窗口"""
        if self.file_selection_window and self.file_selection_window.winfo_exists():
            self.file_selection_window.destroy()
        
        self.file_selection_window = tk.Toplevel(self.root)
        self.file_selection_window.title("选择要下载的文件")
        self.file_selection_window.geometry("800x600")
        self.file_selection_window.transient(self.root)
        
        # 主框架
        main_frame = ttk.Frame(self.file_selection_window, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # 顶部信息
        info_frame = ttk.Frame(main_frame)
        info_frame.pack(fill=tk.X, pady=(0, 10))
        
        total_size = sum(f[2] for f in files)
        ttk.Label(info_frame, text=f"总计 {len(files)} 个文件，总大小: {self.downloader.format_size(total_size)}",
                 font=('', 10, 'bold')).pack(side=tk.LEFT)
        
        # 搜索框
        search_frame = ttk.Frame(main_frame)
        search_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(search_frame, text="过滤:").pack(side=tk.LEFT, padx=(0, 5))
        search_var = tk.StringVar()
        search_entry = ttk.Entry(search_frame, textvariable=search_var, width=40)
        search_entry.pack(side=tk.LEFT, padx=(0, 10))
        
        # 快速选择按钮
        ttk.Button(search_frame, text="全选", 
                  command=lambda: self._select_all_files(tree, file_items, update_selection_count)).pack(side=tk.LEFT, padx=2)
        ttk.Button(search_frame, text="反选", 
                  command=lambda: self._invert_selection(tree, file_items, update_selection_count)).pack(side=tk.LEFT, padx=2)
        ttk.Button(search_frame, text="清空", 
                  command=lambda: self._clear_selection(tree, file_items, update_selection_count)).pack(side=tk.LEFT, padx=2)
        
        # 文件列表（使用Treeview带复选框）
        list_frame = ttk.Frame(main_frame)
        list_frame.pack(fill=tk.BOTH, expand=True)
        
        # 创建Treeview
        columns = ('size', 'path')
        tree = ttk.Treeview(list_frame, columns=columns, show='tree headings', selectmode='none')
        tree.heading('#0', text='☑')
        tree.heading('path', text='文件名')
        tree.heading('size', text='大小')
        
        tree.column('#0', width=40, stretch=False)
        tree.column('path', width=500)
        tree.column('size', width=120, stretch=False)
        
        # 滚动条
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # 填充文件列表
        file_items = {}  # 存储item_id和文件信息的映射
        for i, (path, url, size) in enumerate(files):
            item_id = tree.insert('', 'end', 
                                 text='☑',
                                 values=(self.downloader.format_size(size), path),
                                 tags=('checked',))
            file_items[item_id] = (path, url, size, True)  # True表示选中
        
        # 点击切换选中状态
        def toggle_item(event):
            item = tree.identify_row(event.y)
            if item:
                current_state = file_items[item][3]
                new_state = not current_state
                tree.item(item, text='☑' if new_state else '☐')
                path, url, size, _ = file_items[item]
                file_items[item] = (path, url, size, new_state)
                update_selection_count()
        
        tree.bind('<Button-1>', toggle_item)
        
        # 搜索过滤功能
        def filter_files(*args):
            query = search_var.get().lower()
            for item in tree.get_children():
                path = file_items[item][0]
                if query in path.lower():
                    tree.reattach(item, '', 'end')
                else:
                    tree.detach(item)
            update_selection_count()
        
        search_var.trace('w', filter_files)
        
        # 底部信息和按钮
        bottom_frame = ttk.Frame(main_frame)
        bottom_frame.pack(fill=tk.X, pady=(10, 0))
        
        selection_label = ttk.Label(bottom_frame, text="")
        selection_label.pack(side=tk.LEFT)
        
        def update_selection_count():
            visible_items = tree.get_children()
            selected = sum(1 for item in visible_items if file_items[item][3])
            selected_size = sum(file_items[item][2] for item in visible_items if file_items[item][3])
            selection_label.config(
                text=f"已选择: {selected} 个文件 ({self.downloader.format_size(selected_size)})")
        
        update_selection_count()
        
        button_frame = ttk.Frame(bottom_frame)
        button_frame.pack(side=tk.RIGHT)
        
        def start_selected_download():
            selected_files = [(path, url, size) for item, (path, url, size, checked) in file_items.items() 
                            if checked and item in tree.get_children()]
            
            if not selected_files:
                messagebox.showwarning("警告", "请至少选择一个文件")
                return
            
            self.file_queue = selected_files
            self.current_file_index = 0
            
            self.file_selection_window.destroy()
            self.log_message(f"\n已选择 {len(selected_files)} 个文件开始下载")
            
            # 显示选中的文件
            for i, (path, _, size) in enumerate(selected_files[:5], 1):
                self.log_message(f"  - {path} ({self.downloader.format_size(size)})")
            if len(selected_files) > 5:
                self.log_message(f"  ... 还有 {len(selected_files)-5} 个文件")
            
            self._enable_download_controls()
            self._download_next_file(save_dir)
        
        ttk.Button(button_frame, text="开始下载", 
                  command=start_selected_download).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="取消", 
                  command=self.file_selection_window.destroy).pack(side=tk.LEFT)
    
    def _select_all_files(self, tree, file_items, update_callback):
        """全选文件"""
        for item in tree.get_children():
            tree.item(item, text='☑')
            path, url, size, _ = file_items[item]
            file_items[item] = (path, url, size, True)
        update_callback()
    
    def _invert_selection(self, tree, file_items, update_callback):
        """反选文件"""
        for item in tree.get_children():
            current_state = file_items[item][3]
            new_state = not current_state
            tree.item(item, text='☑' if new_state else '☐')
            path, url, size, _ = file_items[item]
            file_items[item] = (path, url, size, new_state)
        update_callback()
    
    def _clear_selection(self, tree, file_items, update_callback):
        """清空选择"""
        for item in tree.get_children():
            tree.item(item, text='☐')
            path, url, size, _ = file_items[item]
            file_items[item] = (path, url, size, False)
        update_callback()
    
    def _enable_download_controls(self):
        """启用下载控制按钮"""
        self.download_btn['state'] = tk.DISABLED
        self.pause_btn['state'] = tk.NORMAL
        self.cancel_btn['state'] = tk.NORMAL
        self.is_downloading = True
    
    def _download_next_file(self, save_dir):
        """下载队列中的下一个文件"""
        if self.current_file_index >= len(self.file_queue):
            # 所有文件下载完成
            self.log_message("✅ 所有文件下载完成！")
            self._download_finished(True)
            return
        
        relative_path, download_url, file_size = self.file_queue[self.current_file_index]
        
        # 更新批量进度
        self.batch_label.config(text=f"整体进度: {self.current_file_index + 1}/{len(self.file_queue)} 文件")
        self.log_message(f"\n⬇️ [{self.current_file_index + 1}/{len(self.file_queue)}] 下载: {relative_path}")
        
        # 确保子目录存在
        save_path = os.path.join(save_dir, relative_path)
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        
        # 在新线程中下载
        self.download_thread = threading.Thread(
            target=self._batch_download_worker,
            args=(download_url, save_path, save_dir),
            daemon=True
        )
        self.download_thread.start()
    
    def _batch_download_worker(self, url, save_path, save_dir):
        """批量下载工作线程"""
        success = self.downloader.download_file(
            url,
            save_path,
            progress_callback=self.update_progress,
            status_callback=self.update_status
        )
        
        if success or not self.is_downloading:  # 成功或已取消
            self.current_file_index += 1
            if self.is_downloading:  # 如果没有取消，继续下一个
                self.root.after(0, lambda: self._download_next_file(save_dir))
        else:
            # 下载失败
            self.root.after(0, lambda: self._download_finished(False))
    
    def _download_worker(self, url, save_path):
        """下载工作线程"""
        success = self.downloader.download_file(
            url,
            save_path,
            progress_callback=self.update_progress,
            status_callback=self.update_status
        )
        
        self.is_downloading = False
        
        # 更新按钮状态
        self.root.after(0, self._download_finished, success)
    
    def _download_finished(self, success):
        """下载完成后的处理"""
        self.download_btn['state'] = tk.NORMAL
        self.pause_btn['state'] = tk.DISABLED
        self.cancel_btn['state'] = tk.DISABLED
        
        if success:
            messagebox.showinfo("完成", "文件下载完成！")
        else:
            messagebox.showwarning("提示", "下载未完成，请查看日志")
    
    def pause_download(self):
        """暂停/恢复下载"""
        if self.downloader.pause_flag:
            self.downloader.resume_download()
            self.pause_btn['text'] = "暂停"
            self.log_message("恢复下载...")
        else:
            self.downloader.pause_download()
            self.pause_btn['text'] = "恢复"
            self.log_message("已暂停下载")
    
    def cancel_download(self):
        """取消下载"""
        if messagebox.askyesno("确认", "确定要取消下载吗？"):
            self.downloader.cancel_download()
            self.is_downloading = False  # 停止批量下载队列
            self.log_message("正在取消下载...")


def main():
    """主函数"""
    root = tk.Tk()
    app = DownloaderGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
