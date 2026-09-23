"""
根目录 WebUI 启动入口
自动加载并运行 agent/webui.py
"""

from agent.webui import start_server

if __name__ == "__main__":
    start_server(host="127.0.0.1", port=8000)

