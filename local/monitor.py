#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MiniMax API 使用量监控工具
"""

import json
import os
import sys
import time
import argparse
import threading
from datetime import datetime, timedelta
from pathlib import Path

import requests
import yaml


class Config:
    """配置管理"""
    def __init__(self, config_path="config.yaml"):
        self.config_path = config_path
        self._load()

    def _load(self):
        with open(self.config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        self.api_key = config.get('api_key', '')
        self.api_url = config.get('api_url', 'https://www.minimaxi.com/v1/api/openplatform/coding_plan/remains')
        self.interval_minutes = config.get('monitor', {}).get('interval_minutes', 30)
        self.record_before_seconds = config.get('monitor', {}).get('record_before_seconds', 300)
        self.cycle_hours = config.get('monitor', {}).get('cycle_hours', 5)
        # 远程配置
        self.cloud_function_url = config.get('remote', {}).get('cloud_function_url', '')
        self.cos_url = config.get('remote', {}).get('cos_url', '')


class DataStorage:
    """数据存储"""
    def __init__(self, data_file="usage_data.json"):
        self.data_file = data_file

    def load(self):
        """加载历史数据"""
        if os.path.exists(self.data_file):
            with open(self.data_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return []

    def save(self, records):
        """保存数据"""
        with open(self.data_file, 'w', encoding='utf-8') as f:
            json.dump(records, f, ensure_ascii=False, indent=2)

    def add_record(self, data):
        """添加记录"""
        records = self.load()
        # 检查是否已经存在相同时间的记录（避免重复）
        timestamp = data.get('timestamp')
        if not any(r.get('timestamp') == timestamp for r in records):
            records.append(data)
            self.save(records)
            return True
        return False


class MiniMaxMonitor:
    """MiniMax 用量监控器"""

    def __init__(self, config):
        self.config = config
        self.storage = DataStorage()
        self.monitor_thread = None
        self.stop_event = threading.Event()

    def query(self):
        """查询当前用量"""
        headers = {
            'Authorization': f'Bearer {self.config.api_key}',
            'Content-Type': 'application/json'
        }

        try:
            response = requests.get(self.config.api_url, headers=headers, timeout=30)
            response.raise_for_status()
            data = response.json()
            return data
        except requests.exceptions.RequestException as e:
            print(f"请求失败: {e}")
            return None

    def get_current_usage_info(self):
        """获取当前用量信息并格式化输出"""
        result = self.query()
        if not result:
            return None

        # 解析数据
        try:
            model_remains = result.get('model_remains', [])
            if not model_remains:
                return None

            # 取第一个模型的数据
            data = model_remains[0]
            total_count = data.get('current_interval_total_count', 0)
            used_count = data.get('current_interval_usage_count', 0)  # API返回的就是使用次数
            remains_time = data.get('remains_time', 0)  # 毫秒

            # 时间戳
            start_time = data.get('start_time', 0)
            end_time = data.get('end_time', 0)

            info = {
                'timestamp': datetime.now().isoformat(),
                'total_count': total_count,
                'used_count': used_count,
                'remains_time_ms': remains_time,
                'remains_time_hours': round(remains_time / 3600000, 2),
                'cycle_start': datetime.fromtimestamp(start_time/1000).isoformat() if start_time else None,
                'cycle_end': datetime.fromtimestamp(end_time/1000).isoformat() if end_time else None,
            }
            return info
        except (KeyError, TypeError) as e:
            print(f"解析数据失败: {e}")
            print(f"原始响应: {result}")
            return None

    def print_usage(self, info):
        """打印用量信息"""
        if not info:
            return

        print("\n" + "="*50)
        print(f"查询时间:    {info['timestamp']}")
        print(f"周期开始:    {info.get('cycle_start', 'N/A')}")
        print(f"周期结束:    {info.get('cycle_end', 'N/A')}")
        print(f"剩余时间:   {info['remains_time_hours']} 小时")
        print(f"剩余次数:   {info['used_count']}")
        print(f"总次数:     {info['total_count']}")
        print("="*50 + "\n")

    def record_current_usage(self):
        """记录当前用量"""
        info = self.get_current_usage_info()
        if info:
            if self.storage.add_record(info):
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 记录成功: 剩余 {info['remains_time_hours']} 小时, 剩余 {info['used_count']} 次")
            else:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 记录已存在，跳过")
            return info
        return None

    def start_monitor(self):
        """启动定时监控"""
        print(f"启动监控: 每 {self.config.interval_minutes} 分钟检查一次")
        print(f"周期结束前 {self.config.record_before_seconds} 秒会自动记录最后用量")
        print("按 Ctrl+C 停止监控\n")

        interval_seconds = self.config.interval_minutes * 60
        cycle_seconds = self.config.cycle_hours * 3600

        next_cycle_end = None
        last_record_hour = -1

        while not self.stop_event.is_set():
            now = datetime.now()

            # 记录当前小时
            current_hour = now.hour

            # 检查是否需要记录（每小时记录一次）
            if current_hour != last_record_hour:
                self.record_current_usage()
                last_record_hour = current_hour

            # 计算当前5小时周期的结束时间
            # 假设周期从 0:00, 5:00, 10:00, 15:00, 20:00 开始
            cycle_starts = [0, 5, 10, 15, 20]
            current_cycle_start = max([h for h in cycle_starts if h <= now.hour], default=0)
            if now.hour < current_cycle_start:
                current_cycle_start = cycle_starts[cycle_starts.index(current_cycle_start) - 1]

            cycle_end_time = now.replace(hour=current_cycle_start, minute=0, second=0, microsecond=0)
            if now.hour >= current_cycle_start:
                cycle_end_time += timedelta(hours=5)

            time_until_end = (cycle_end_time - now).total_seconds()

            # 检查是否接近周期结束（5分钟内）
            if 0 < time_until_end <= self.config.record_before_seconds:
                print(f"[{now.strftime('%H:%M:%S')}] 检测到周期即将结束，额外记录最后用量...")

                # 用完整时间戳记录，精确到秒，避免重复
                info = self.get_current_usage_info()
                if info:
                    info['timestamp'] = (now + timedelta(seconds=5)).isoformat()
                    if self.storage.add_record(info):
                        print(f"[{now.strftime('%H:%M:%S')}] 周期结束前记录成功!")
                # 等待一会儿避免重复记录
                time.sleep(60)

            # 等待下一次检查
            self.stop_event.wait(interval_seconds)

        print("监控已停止")

    def stop_monitor(self):
        """停止监控"""
        self.stop_event.set()


def show_history():
    """显示历史记录"""
    storage = DataStorage()
    records = storage.load()

    if not records:
        print("暂无历史记录")
        return

    print(f"\n历史记录 (共 {len(records)} 条):\n")
    print(f"{'时间':<25} {'剩余时间':<12} {'剩余次数':<10} {'总次数':<10}")
    print("-" * 65)

    for r in records:
        remains_hours = r.get('remains_time_hours', 0)
        print(f"{r['timestamp']:<25} {remains_hours:<12} {r['used_count']:<10} {r['total_count']:<10}")

    print()


def main():
    parser = argparse.ArgumentParser(description='MiniMax API 用量监控工具')
    parser.add_argument('command', choices=['query', 'monitor', 'history'],
                        help='命令: query=查询当前, monitor=启动监控, history=查看历史')

    args = parser.parse_args()

    # 检查配置文件
    if not os.path.exists('config.yaml'):
        print("错误: 配置文件 config.yaml 不存在")
        sys.exit(1)

    config = Config()
    if not config.api_key or config.api_key == "your-api-key-here":
        print("错误: 请在 config.yaml 中配置有效的 API Key")
        sys.exit(1)

    monitor = MiniMaxMonitor(config)

    if args.command == 'query':
        info = monitor.get_current_usage_info()
        monitor.print_usage(info)

    elif args.command == 'monitor':
        def signal_handler(sig, frame):
            print("\n正在停止监控...")
            monitor.stop_monitor()
            sys.exit(0)

        import signal
        signal.signal(signal.SIGINT, signal_handler)

        monitor.start_monitor()

    elif args.command == 'history':
        show_history()


if __name__ == '__main__':
    main()
