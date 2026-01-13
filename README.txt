HuggingFace 下载工具 v2.0
================================

功能特点：
---------
✅ 支持断点续传 - 下载中断后可以继续下载
✅ 支持批量下载 - 一键下载整个模型/目录
✅ 自定义保存路径 - 可选择文件保存位置
✅ 图形界面操作 - 简单易用
✅ 实时显示下载进度和速度
✅ 支持暂停/恢复/取消下载
✅ 自动保持目录结构

快速开始：
---------

【方法一：直接运行（推荐）】
1. 双击运行 "启动.bat"
2. 或者直接运行 "HF下载工具.exe"（如果已打包）

【方法二：Python运行】
1. 安装依赖：pip install -r requirements.txt
2. 运行程序：python hf_downloader.py

使用说明：
---------

【单文件下载模式】
1. 选择"单文件下载"模式
2. 粘贴单个文件的URL，例如：
   https://hf-mirror.com/username/model/resolve/main/model.bin
   https://hf-mirror.com/username/model/blob/main/config.json
3. 选择保存路径
4. 可选：修改文件名
5. 点击"开始下载"

【批量下载模式】（下载整个模型）
1. 选择"批量下载（整个模型/目录）"模式
2. 粘贴模型主页URL，例如：
   https://hf-mirror.com/LiquidAI/LFM2.5-1.2B-Instruct/tree/main
   https://hf-mirror.com/username/model/tree/main
   https://hf-mirror.com/username/model/tree/main/subfolder
3. 选择保存路径（会自动创建子文件夹）
4. 点击"开始下载"
5. 程序会自动：
   - 获取所有文件列表
   - 显示文件数量和总大小
   - 按顺序下载所有文件
   - 保持原有目录结构

下载控制：
---------
- 暂停：点击"暂停"按钮，再次点击恢复
- 取消：点击"取消"按钮停止下载
- 断点续传：下载中断后，使用相同URL和路径重新开始，自动从断点继续

支持的URL格式：
--------------
单文件：
  - https://hf-mirror.com/用户名/模型名/resolve/分支/文件路径
  - https://hf-mirror.com/用户名/模型名/blob/分支/文件路径
  - https://huggingface.co/用户名/模型名/resolve/分支/文件路径

整个模型/目录：
  - https://hf-mirror.com/用户名/模型名/tree/分支
  - https://hf-mirror.com/用户名/模型名/tree/分支/子目录
  - https://huggingface.co/用户名/模型名/tree/分支

注意事项：
---------
- 确保网络连接正常
- 保存路径必须有足够的磁盘空间
- 批量下载大模型时，请预留充足的磁盘空间
- 断点续传需要服务器支持（HuggingFace 镜像站支持）
- 批量下载时，每个文件都支持断点续传

打包发布：
---------
如果需要打包成独立exe程序：
1. 双击运行 "build.bat"
2. 等待打包完成
3. 在 dist 文件夹中找到 "HF下载工具.exe"
4. 将该exe文件分发给其他用户即可直接使用，无需安装Python

技术支持：
---------
- 基于 Python 3.x
- 使用 tkinter 构建图形界面
- 使用 requests 实现HTTP下载
- 使用 HuggingFace API 获取文件列表
