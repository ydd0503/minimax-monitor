#!/usr/bin/env python3
"""
简单的HTTP服务器，用于托管MiniMax监控页面
"""
import http.server
import socketserver
import json
import os
import requests
import yaml
from datetime import datetime, timedelta

PORT = 8080

# 配置缓存
_config = None

def load_config():
    """加载配置文件"""
    global _config
    if _config is None:
        config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.yaml')
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                _config = yaml.safe_load(f)
        else:
            _config = {}
    return _config

def get_api_key():
    """从 config.yaml 获取 API Key"""
    config = load_config()
    return config.get('api_key', '')

def get_api_url():
    """从 config.yaml 获取 API URL"""
    config = load_config()
    return config.get('api_url', 'https://www.minimaxi.com/v1/api/openplatform/coding_plan/remains')
    if os.path.exists(config_path):
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
            return config.get('api_key', '')
    return ''

def fetch_current_usage():
    """获取当前用量"""
    api_key = get_api_key()
    if not api_key:
        return None

    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json'
    }

    try:
        api_url = get_api_url()
        response = requests.get(api_url, headers=headers, timeout=30)
        data = response.json()
        info = data.get("model_remains", [{}])[0]

        now = datetime.now()
        cycle_start_default = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        cycle_end_default = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()

        return {
            "timestamp": now.isoformat(),
            "total_count": info.get("current_interval_total_count", 0),
            "used_count": info.get("current_interval_usage_count", 0),
            "remain_count": info.get("current_interval_total_count", 0) - info.get("current_interval_usage_count", 0),
            "remains_time_ms": info.get("remains_time", 0),
            "remains_time_hours": info.get("remains_time", 0) / 3600000,
            "cycle_start": info.get("current_interval_start_time", cycle_start_default),
            "cycle_end": info.get("current_interval_end_time", cycle_end_default)
        }
    except Exception as e:
        print(f"获取用量失败: {e}")
        return None

class MyHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        super().end_headers()

    def do_GET(self):
        if self.path == '/api/config':
            # 返回配置信息
            config = load_config()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()

            # 只返回必要的配置，不返回敏感信息
            response = {
                'api_url': config.get('api_url', ''),
                'cloud_function_url': config.get('remote', {}).get('cloud_function_url', ''),
                'cos_url': config.get('remote', {}).get('cos_url', '')
            }
            self.wfile.write(json.dumps(response).encode())
        elif self.path == '/api/current':
            # 返回实时数据
            record = fetch_current_usage()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()

            if record:
                # 转换为与云函数相同的格式
                self.wfile.write(json.dumps({'model_remains': [record]}).encode())
            else:
                self.wfile.write(json.dumps({'error': '获取数据失败，请检查config.yaml配置'}).encode())
        elif self.path == '/api/history':
            # 返回历史数据
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()

            # 读取历史数据文件（数据在上级目录）
            data_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'usage_data.json')
            if os.path.exists(data_file):
                with open(data_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self.wfile.write(json.dumps(data).encode())
            else:
                self.wfile.write(b'[]')
        else:
            # 默认返回静态文件
            super().do_GET()

os.chdir(os.path.dirname(os.path.abspath(__file__)))

with socketserver.TCPServer(("", PORT), MyHTTPRequestHandler) as httpd:
    print(f"服务器已启动: http://localhost:{PORT}")
    print(f"按 Ctrl+C 停止服务器")
    httpd.serve_forever()
