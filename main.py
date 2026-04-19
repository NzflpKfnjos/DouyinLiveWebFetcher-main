#!/usr/bin/python
# coding:utf-8

# @FileName:    main.py
# @Time:        2024/1/2 22:27
# @Author:      bubu
# @Project:     douyinLiveWebFetcher

import argparse

from liveMan import DouyinLiveWebFetcher
from web_server import LiveMessageWebApp


DEFAULT_LIVE_ID = '333169018618'


def parse_args():
    parser = argparse.ArgumentParser(description='Douyin live chat viewer')
    parser.add_argument('--live-id', default=DEFAULT_LIVE_ID, help='抖音直播间 live id')
    parser.add_argument('--mode', choices=['web', 'console'], default='web', help='启动模式')
    parser.add_argument('--host', default='127.0.0.1', help='网页模式监听地址')
    parser.add_argument('--port', type=int, default=8000, help='网页模式监听端口')
    return parser.parse_args()


if __name__ == '__main__':
    args = parse_args()

    if args.mode == 'console':
        room = DouyinLiveWebFetcher(args.live_id)
        room.start()
    else:
        app = LiveMessageWebApp(args.live_id, host=args.host, port=args.port)
        app.run()
