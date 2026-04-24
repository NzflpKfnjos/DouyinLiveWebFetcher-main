#!/usr/bin/python
# coding:utf-8

# @FileName:    main.py
# @Time:        2024/1/2 22:27
# @Author:      bubu
# @Project:     douyinLiveWebFetcher

import argparse
import json
import os
from pathlib import Path

from liveMan import DouyinLiveWebFetcher
from web_server import LiveMessageWebApp


DEFAULT_LIVE_ID = 'LYG9199'
ENV_FILE = Path(__file__).resolve().parent / '.env'


def _strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _cookie_json_to_header(value: str) -> str:
    text = _strip_quotes(value)
    if not text.lstrip().startswith('{'):
        return text

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return text

    if not isinstance(parsed, dict):
        return text

    return '; '.join(
        f'{key}={cookie_value}'
        for key, cookie_value in parsed.items()
        if cookie_value is not None
    )


def _normalize_env_value(key: str, value: str) -> str:
    value = _strip_quotes(value)
    if key == 'DOUYIN_COOKIE':
        return _cookie_json_to_header(value)
    return value


def _iter_dotenv_assignments(text: str):
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        raw_line = lines[index]
        line = raw_line.strip()
        index += 1
        if not line or line.startswith('#') or '=' not in line:
            continue

        key, value = line.split('=', 1)
        key = key.strip()
        value_lines = [value.rstrip()]

        stripped_value = value.strip()
        if stripped_value.startswith('{'):
            brace_balance = stripped_value.count('{') - stripped_value.count('}')
            while brace_balance > 0 and index < len(lines):
                continuation = lines[index].rstrip()
                index += 1
                value_lines.append(continuation)
                brace_balance += continuation.count('{') - continuation.count('}')

        yield key, '\n'.join(value_lines)


def load_dotenv(env_file: Path = ENV_FILE):
    if not env_file.exists():
        return

    for key, value in _iter_dotenv_assignments(env_file.read_text(encoding='utf-8')):
        if not key or key in os.environ:
            continue
        os.environ[key] = _normalize_env_value(key, value)


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
    args.cookie = _cookie_json_to_header(args.cookie)
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
