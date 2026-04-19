#!/usr/bin/python
# coding:utf-8

# @FileName:    main.py
# @Time:        2024/1/2 22:27
# @Author:      bubu
# @Project:     douyinLiveWebFetcher

import argparse
import os
from pathlib import Path

from liveMan import DouyinLiveWebFetcher
from web_server import LiveMessageWebApp


DEFAULT_LIVE_ID = '33045748685'
ENV_FILE = Path(__file__).resolve().parent / '.env'


def load_dotenv(env_file: Path = ENV_FILE):
    if not env_file.exists():
        return

    for raw_line in env_file.read_text(encoding='utf-8').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        if not key or key in os.environ:
            continue

        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ[key] = value


def parse_args():
    parser = argparse.ArgumentParser(description='Douyin live chat viewer')
    parser.add_argument('--live-id', default=DEFAULT_LIVE_ID, help='抖音直播间 live id')
    parser.add_argument('--mode', choices=['web', 'console'], default='web', help='启动模式')
    parser.add_argument('--host', default='127.0.0.1', help='网页模式监听地址')
    parser.add_argument('--port', type=int, default=8000, help='网页模式监听端口')
    parser.add_argument('--cookie', default=os.getenv('DOUYIN_COOKIE', ''),
                        help='Douyin cookie string. You can also set DOUYIN_COOKIE.')
    args = parser.parse_args()
    if args.cookie.strip().lower() == 'default':
        args.cookie = os.getenv('DOUYIN_COOKIE', '')
    return args


if __name__ == '__main__':
    load_dotenv()
    args = parse_args()

    if args.mode == 'console':
        room = DouyinLiveWebFetcher(args.live_id, cookie=args.cookie)
        room.start()
    else:
        app = LiveMessageWebApp(args.live_id, host=args.host, port=args.port, cookie=args.cookie)
        app.run()
