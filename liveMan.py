#!/usr/bin/python
# coding:utf-8

# @FileName:    liveMan.py
# @Time:        2024/1/2 21:51
# @Author:      bubu
# @Project:     douyinLiveWebFetcher

import codecs
import gzip
import hashlib
import json
import random
import re
import string
import subprocess
import threading
import time
import execjs
import urllib.parse
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Callable, Optional
from unittest.mock import patch

import requests
import websocket
from py_mini_racer import MiniRacer

from ac_signature import get__ac_signature
from protobuf.douyin import *

from urllib3.util.url import parse_url


def execute_js(js_file: str):
    """
    执行 JavaScript 文件
    :param js_file: JavaScript 文件路径
    :return: 执行结果
    """
    with open(js_file, 'r', encoding='utf-8') as file:
        js_code = file.read()
    
    ctx = execjs.compile(js_code)
    return ctx


@contextmanager
def patched_popen_encoding(encoding='utf-8'):
    original_popen_init = subprocess.Popen.__init__
    
    def new_popen_init(self, *args, **kwargs):
        kwargs['encoding'] = encoding
        original_popen_init(self, *args, **kwargs)
    
    with patch.object(subprocess.Popen, '__init__', new_popen_init):
        yield


def generateSignature(wss, script_file='sign.js'):
    """
    出现gbk编码问题则修改 python模块subprocess.py的源码中Popen类的__init__函数参数encoding值为 "utf-8"
    """
    params = ("live_id,aid,version_code,webcast_sdk_version,"
              "room_id,sub_room_id,sub_channel_id,did_rule,"
              "user_unique_id,device_platform,device_type,ac,"
              "identity").split(',')
    wss_params = urllib.parse.urlparse(wss).query.split('&')
    wss_maps = {i.split('=')[0]: i.split("=")[-1] for i in wss_params}
    tpl_params = [f"{i}={wss_maps.get(i, '')}" for i in params]
    param = ','.join(tpl_params)
    md5 = hashlib.md5()
    md5.update(param.encode())
    md5_param = md5.hexdigest()
    
    with codecs.open(script_file, 'r', encoding='utf8') as f:
        script = f.read()
    
    ctx = MiniRacer()
    ctx.eval(script)
    
    try:
        signature = ctx.call("get_sign", md5_param)
        return signature
    except Exception as e:
        print(e)
    
    # 以下代码对应js脚本为sign_v0.js
    # context = execjs.compile(script)
    # with patched_popen_encoding(encoding='utf-8'):
    #     ret = context.call('getSign', {'X-MS-STUB': md5_param})
    # return ret.get('X-Bogus')


def generateMsToken(length=182):
    """
    产生请求头部cookie中的msToken字段，其实为随机的107位字符
    :param length:字符位数
    :return:msToken
    """
    random_str = ''
    base_str = string.ascii_letters + string.digits + '-_'
    _len = len(base_str) - 1
    for _ in range(length):
        random_str += base_str[random.randint(0, _len)]
    return random_str


class DouyinLiveWebFetcher:
    MESSAGE_PARSER_NAMES = {
        'WebcastChatMessage': '_parseChatMsg',  # 聊天消息
        'WebcastGiftMessage': '_parseGiftMsg',  # 礼物消息
        'WebcastLikeMessage': '_parseLikeMsg',  # 点赞消息
        'WebcastMemberMessage': '_parseMemberMsg',  # 进入直播间消息
        'WebcastSocialMessage': '_parseSocialMsg',  # 关注消息
        'WebcastRoomUserSeqMessage': '_parseRoomUserSeqMsg',  # 直播间统计
        'WebcastFansclubMessage': '_parseFansclubMsg',  # 粉丝团消息
        'WebcastControlMessage': '_parseControlMsg',  # 直播间状态消息
        'WebcastEmojiChatMessage': '_parseEmojiChatMsg',  # 聊天表情包消息
        'WebcastInRoomBannerMessage': '_parseInRoomBannerMsg',  # 直播间横幅消息
        'WebcastRoomStatsMessage': '_parseRoomStatsMsg',  # 直播间统计信息
        'WebcastRoomMessage': '_parseRoomMsg',  # 直播间信息
        'WebcastRoomRankMessage': '_parseRankMsg',  # 直播间排行榜信息
        'WebcastRoomStreamAdaptationMessage': '_parseRoomStreamAdaptationMsg',  # 直播间流配置
    }

    
    def __init__(self, live_id, abogus_file='a_bogus.js', event_handler: Optional[Callable[[dict], None]] = None,
                 verbose=True, cookie: str = ''):
        """
        直播间弹幕抓取对象
        :param live_id: 直播间的直播id，打开直播间web首页的链接如：https://live.douyin.com/261378947940，
                        其中的261378947940即是live_id
        """
        self.abogus_file = abogus_file
        self.cookie = (cookie or '').strip()
        self.__ttwid = None
        self.__room_id = None
        self.session = requests.Session()
        self.live_id = live_id
        self.event_handler = event_handler
        self.verbose = verbose
        self._message_parsers = {
            method: getattr(self, parser_name)
            for method, parser_name in self.MESSAGE_PARSER_NAMES.items()
        }
        self._recent_gift_events = {}
        self._recent_gift_events_next_prune = 0.0
        self.host = "https://www.douyin.com/"
        self.live_url = "https://live.douyin.com/"
        self.ws = None
        self._stop_event = threading.Event()
        self._heartbeat_thread = None
        self._heartbeat_interval_seconds = 10.0
        self._reconnect_delay_seconds = 2.0
        self.user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36 Edg/140.0.0.0"
        self.headers = {
            'User-Agent': self.user_agent
        }
        if self.cookie:
            self.headers['Cookie'] = self.cookie
            self.session.headers.update({'Cookie': self.cookie})
    
    def start(self):
        self._stop_event.clear()
        while not self._stop_event.is_set():
            try:
                self._connectFetchLoop()
            except Exception as err:
                if self._stop_event.is_set():
                    break
                self._log("WebSocket reconnect error:", err)
                self._emit_event(
                    'connection',
                    status='error',
                    message=str(err),
                    live_id=self.live_id,
                    room_id=self.room_id,
                )

            if self._stop_event.is_set():
                break

            self._emit_event(
                'connection',
                status='reconnecting',
                message=f'{self._reconnect_delay_seconds:.0f}s',
                live_id=self.live_id,
                room_id=self.room_id,
            )
            time.sleep(self._reconnect_delay_seconds)
    
    def stop(self):
        self._stop_event.set()
        if self.ws is not None:
            try:
                self.ws.close()
            except Exception:
                pass

    def _log(self, *args):
        if self.verbose:
            print(*args)

    def _build_event(self, event_type, **payload):
        return {
            "type": event_type,
            "timestamp": int(time.time() * 1000),
            "iso_time": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            **payload,
        }

    def _emit_event(self, event_type, **payload):
        if self.event_handler is None:
            return
        event = self._build_event(event_type, **payload)
        try:
            self.event_handler(event)
        except Exception as err:
            self._log("Event handler error:", err)

    @staticmethod
    def _first_positive_value(*values, default=0):
        for value in values:
            if value:
                return value
        return default

    @staticmethod
    def _image_urls(image):
        if image is None:
            return []
        return list(getattr(image, 'url_list_list', []) or [])

    def _first_image_urls(self, *images):
        for image in images:
            urls = self._image_urls(image)
            if urls:
                return urls
        return []

    @staticmethod
    def _is_gift_method(method):
        method = method or ''
        method_lower = method.lower()
        if any(word in method_lower for word in ('vote', 'sort', 'rank', 'guide')):
            return False
        return method_lower.startswith('webcastgift') and 'message' in method_lower

    @staticmethod
    def _is_probable_gift_text(text):
        if not text:
            return False
        gift_words = ('送出', '送了', '赠送', '礼物', 'diamond', '钻石', '抖币')
        excluded_words = (
            '礼物展馆', '礼物面板', 'gift_panel', 'giftpanel', 'gift_sort', 'gift_vote',
            'gift_task', 'quota_task', 'condition_', 'instance', '多阶段任务',
            'anchor_flow', 'anchor_mvp', 'revenue', 'webcast_revenue',
        )
        text_lower = str(text).lower()
        return any(word in text_lower for word in gift_words) and not any(word in text_lower for word in excluded_words)

    @staticmethod
    def _short_text(value):
        if isinstance(value, list):
            return ''.join(str(item) for item in value if item is not None)
        if value is None:
            return ''
        return str(value)

    def _remember_gift_event(self, signature, ttl_seconds=30):
        now = time.time()
        recent_events = self._recent_gift_events
        created_at = recent_events.get(signature)
        if created_at is not None:
            if now - created_at < ttl_seconds:
                return False
            del recent_events[signature]

        # This method runs on every gift-like event.  Rebuilding the whole TTL
        # dictionary on each call makes high-message rooms pay O(n) work per
        # event.  Prune in place at most once per second so normal dedupe
        # remains O(1) while stale signatures are still bounded by the same TTL
        # window.
        if now >= self._recent_gift_events_next_prune:
            expired_before = now - ttl_seconds
            for key, created_at in list(recent_events.items()):
                if created_at < expired_before:
                    del recent_events[key]
            self._recent_gift_events_next_prune = now + 1.0

        recent_events[signature] = now
        return True

    @staticmethod
    def _text_has_gift_piece(text):
        for piece in getattr(text, 'pieces_list', []) or []:
            gift_value = getattr(piece, 'gift_value', None)
            if not gift_value:
                continue
            name_ref = getattr(gift_value, 'name_ref', None)
            if getattr(gift_value, 'gift_id', 0) or getattr(name_ref, 'default_pattern', ''):
                return True
        return False

    @staticmethod
    def _gift_name_from_text_pieces(text):
        for piece in getattr(text, 'pieces_list', []) or []:
            gift_value = getattr(piece, 'gift_value', None)
            if not gift_value:
                continue
            name_ref = getattr(gift_value, 'name_ref', None)
            gift_name = getattr(name_ref, 'default_pattern', '') if name_ref else ''
            if gift_name:
                return gift_name
        return ''

    @staticmethod
    def _gift_id_from_text_pieces(text):
        for piece in getattr(text, 'pieces_list', []) or []:
            gift_value = getattr(piece, 'gift_value', None)
            gift_id = getattr(gift_value, 'gift_id', 0) if gift_value else 0
            if gift_id:
                return str(gift_id)
        return ''

    @staticmethod
    def _decode_proto_string(value):
        if not isinstance(value, (bytes, bytearray)):
            return ''
        try:
            text = bytes(value).decode('utf-8')
        except UnicodeDecodeError:
            return ''

        text = text.strip()
        if not text or '\x00' in text:
            return ''
        printable_count = sum(1 for char in text if char.isprintable())
        if printable_count / len(text) < 0.8:
            return ''
        return text

    @staticmethod
    def _read_proto_varint(payload, position):
        result = 0
        shift = 0
        while position < len(payload):
            byte = payload[position]
            position += 1
            result |= (byte & 0x7F) << shift
            if byte < 0x80:
                return result, position
            shift += 7
            if shift >= 64:
                break
        raise ValueError('Invalid protobuf varint')

    @classmethod
    def _iter_proto_fields(cls, payload):
        position = 0
        payload_length = len(payload or b'')
        while position < payload_length:
            try:
                key, position = cls._read_proto_varint(payload, position)
            except ValueError:
                break

            field_number = key >> 3
            wire_type = key & 0x07
            if field_number <= 0:
                break

            try:
                if wire_type == 0:
                    value, position = cls._read_proto_varint(payload, position)
                elif wire_type == 1:
                    end_position = position + 8
                    if end_position > payload_length:
                        break
                    value = payload[position:end_position]
                    position = end_position
                elif wire_type == 2:
                    size, position = cls._read_proto_varint(payload, position)
                    end_position = position + size
                    if end_position > payload_length:
                        break
                    value = payload[position:end_position]
                    position = end_position
                elif wire_type == 5:
                    end_position = position + 4
                    if end_position > payload_length:
                        break
                    value = payload[position:end_position]
                    position = end_position
                else:
                    break
            except ValueError:
                break

            yield field_number, wire_type, value

    @classmethod
    def _proto_field_map(cls, payload):
        fields = {}
        for field_number, wire_type, value in cls._iter_proto_fields(payload):
            fields.setdefault(field_number, []).append((wire_type, value))
        return fields

    @staticmethod
    def _first_varint_field(fields, *field_numbers, default=0):
        for field_number in field_numbers:
            for wire_type, value in fields.get(field_number, []):
                if wire_type == 0 and value:
                    return value
        return default

    @staticmethod
    def _message_fields(fields, field_number):
        return [value for wire_type, value in fields.get(field_number, []) if wire_type == 2]

    def _first_message_field(self, fields, *field_numbers):
        for field_number in field_numbers:
            messages = self._message_fields(fields, field_number)
            if messages:
                return messages[0]
        return b''

    def _string_fields(self, fields, field_number):
        strings = []
        for wire_type, value in fields.get(field_number, []):
            if wire_type == 2:
                text = self._decode_proto_string(value)
                if text:
                    strings.append(text)
        return strings

    def _first_string_field(self, fields, *field_numbers):
        for field_number in field_numbers:
            strings = self._string_fields(fields, field_number)
            if strings:
                return strings[0]
        return ''

    def _raw_user_info(self, payload):
        fields = self._proto_field_map(payload)
        user_id = self._first_varint_field(fields, 1)
        user_id = user_id or self._first_string_field(fields, 1028)
        user_name = self._first_string_field(fields, 3, 38)
        return user_id, user_name

    def _find_user_payload(self, fields):
        explicit_payload = self._first_message_field(fields, 7)
        if explicit_payload:
            return explicit_payload

        for field_number, values in fields.items():
            if field_number in {1, 15, 19}:
                continue
            for wire_type, value in values:
                if wire_type != 2:
                    continue
                candidate_fields = self._proto_field_map(value)
                if self._first_varint_field(candidate_fields, 1) and self._first_string_field(candidate_fields, 3):
                    return value
        return b''

    def _raw_image_urls(self, payload):
        fields = self._proto_field_map(payload)
        return [url for url in self._string_fields(fields, 1) if url.startswith(('http://', 'https://'))]

    def _raw_gift_info(self, payload):
        fields = self._proto_field_map(payload)
        image_urls = []
        for image_field_number in (1, 15, 21):
            for image_payload in self._message_fields(fields, image_field_number):
                image_urls = self._raw_image_urls(image_payload)
                if image_urls:
                    break
            if image_urls:
                break

        return {
            'gift_id': self._first_varint_field(fields, 5),
            'gift_name': self._first_string_field(fields, 16, 2),
            'diamond_count': self._first_varint_field(fields, 12),
            'gift_image': image_urls,
        }

    def _find_gift_payload(self, fields):
        explicit_payload = self._first_message_field(fields, 15)
        if explicit_payload:
            return explicit_payload

        for values in fields.values():
            for wire_type, value in values:
                if wire_type != 2:
                    continue
                candidate_fields = self._proto_field_map(value)
                gift_name = self._first_string_field(candidate_fields, 16, 2)
                gift_id = self._first_varint_field(candidate_fields, 5)
                diamond_count = self._first_varint_field(candidate_fields, 12)
                if gift_name and (gift_id or diamond_count):
                    return value
        return b''

    def _raw_text_to_plain(self, payload):
        fields = self._proto_field_map(payload)
        pieces = []
        for piece_payload in self._message_fields(fields, 4):
            piece_fields = self._proto_field_map(piece_payload)
            piece_text = self._first_string_field(piece_fields, 3)
            if not piece_text:
                user_value_payload = self._first_message_field(piece_fields, 4)
                user_payload = self._first_message_field(self._proto_field_map(user_value_payload), 1)
                if user_payload:
                    _, piece_text = self._raw_user_info(user_payload)
            if not piece_text:
                gift_payload = self._first_message_field(piece_fields, 5)
                if gift_payload:
                    gift_fields = self._proto_field_map(gift_payload)
                    name_ref_payload = self._first_message_field(gift_fields, 2)
                    name_ref_fields = self._proto_field_map(name_ref_payload)
                    piece_text = self._first_string_field(name_ref_fields, 2, 1)
            if not piece_text:
                pattern_payload = self._first_message_field(piece_fields, 7)
                pattern_fields = self._proto_field_map(pattern_payload)
                piece_text = self._first_string_field(pattern_fields, 2, 1)
            if piece_text:
                pieces.append(piece_text)
        return ''.join(pieces) or self._first_string_field(fields, 2)

    def _extract_gift_user_from_text(self, text):
        text = str(text or '').strip()
        patterns = (
            r'^(.+?)\s*(?:送出(?:了)?|送了|赠送)\s*[「“\"]?([^「」“”\"\s，。,.!！xX×*]+)',
            r'^(.+?)\s*(?:给主播|给TA|给ta)\s*送(?:出(?:了)?|了)?\s*[「“\"]?([^「」“”\"\s，。,.!！xX×*]+)',
        )
        for pattern in patterns:
            match = re.search(pattern, text)
            if not match:
                continue
            user_name = match.group(1).strip(' ：:，,')
            gift_name = self._clean_gift_name(match.group(2))
            if user_name and gift_name:
                return user_name, gift_name
        return '', ''

    def _decode_raw_gift_payload(self, payload):
        fields = self._proto_field_map(payload)
        user_id, user_name = self._raw_user_info(self._find_user_payload(fields))
        gift_info = self._raw_gift_info(self._find_gift_payload(fields))
        tray_text = self._raw_text_to_plain(self._first_message_field(fields, 19))
        text_user_name, text_gift_name = self._extract_gift_user_from_text(tray_text)
        gift_id = self._first_varint_field(fields, 2) or gift_info.get('gift_id')
        gift_count = self._first_varint_field(fields, 6, 5, 29, 4, default=1)
        return {
            'user_id': user_id,
            'user_name': user_name or text_user_name,
            'gift_id': gift_id,
            'gift_name': gift_info.get('gift_name') or text_gift_name or '',
            'gift_count': gift_count,
            'repeat_count': self._first_varint_field(fields, 5),
            'combo_count': self._first_varint_field(fields, 6),
            'total_count': self._first_varint_field(fields, 29),
            'group_count': self._first_varint_field(fields, 4),
            'diamond_count': gift_info.get('diamond_count') or 0,
            'gift_image': gift_info.get('gift_image') or [],
            'tray_text': tray_text,
        }

    def _iter_json_objects(self, value):
        if isinstance(value, dict):
            yield value
            for child in value.values():
                yield from self._iter_json_objects(child)
        elif isinstance(value, list):
            for child in value:
                yield from self._iter_json_objects(child)

    def _iter_json_strings(self, value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for child in value.values():
                yield from self._iter_json_strings(child)
        elif isinstance(value, list):
            for child in value:
                yield from self._iter_json_strings(child)

    def _first_json_value(self, value, names):
        if isinstance(value, dict):
            for name in names:
                if name in value and value[name] not in (None, ''):
                    return value[name]
            for child in value.values():
                result = self._first_json_value(child, names)
                if result not in (None, ''):
                    return result
        elif isinstance(value, list):
            for child in value:
                result = self._first_json_value(child, names)
                if result not in (None, ''):
                    return result
        return ''

    @staticmethod
    def _clean_gift_name(value):
        text = str(value or '').strip()
        text = re.sub(r'^(礼物|赠礼|送礼)[:：\s]*', '', text)
        text = re.sub(r'\s*[xX×*]\s*\d+.*$', '', text)
        text = re.sub(r'[，。,.!！]+$', '', text)
        return text.strip()

    def _extract_gift_name_from_text(self, text):
        text = str(text or '').strip()
        patterns = (
            r'送(?:出(?:了)?|了|给主播|给TA|给ta)?\s*[「“\"]?([^「」“”\"\s，。,.!！xX×*]+)',
            r'赠送\s*[「“\"]?([^「」“”\"\s，。,.!！xX×*]+)',
            r'礼物[:：\s]+([^\s，。,.!！xX×*]+)',
        )
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                gift_name = self._clean_gift_name(match.group(1))
                if gift_name and gift_name not in {'了', '出', '送'}:
                    return gift_name
        return ''

    @staticmethod
    def _extract_gift_count_from_text(text):
        match = re.search(r'[xX×*]\s*(\d+)', str(text or ''))
        if match:
            return int(match.group(1))
        return 0

    def _extract_banner_json_texts(self, payload):
        texts = []
        for _, wire_type, value in self._iter_proto_fields(payload):
            if wire_type != 2:
                continue
            text = self._decode_proto_string(value)
            if text and text.lstrip().startswith(('{', '[')):
                texts.append(text)
            elif value:
                texts.extend(self._extract_banner_json_texts(value))
        return texts

    def _has_explicit_gift_json_signal(self, value):
        if isinstance(value, dict):
            gift_keys = {
                'gift_name', 'giftName', 'gift_desc', 'giftDesc', 'gift_title', 'giftTitle',
                'gift_id', 'giftId', 'gift_count', 'giftCount', 'repeat_count', 'repeatCount',
            }
            if any(key in value and value.get(key) not in (None, '') for key in gift_keys):
                return True
            return any(self._has_explicit_gift_json_signal(child) for child in value.values())
        if isinstance(value, list):
            return any(self._has_explicit_gift_json_signal(child) for child in value)
        return False

    def _extract_banner_gift_events(self, value):
        events = []
        events_by_signature = {}
        for item in self._iter_json_objects(value):
            combined_text = ' '.join(self._short_text(text) for text in self._iter_json_strings(item))
            text_user_name, text_gift_name = self._extract_gift_user_from_text(combined_text)
            has_text_gift = self._is_probable_gift_text(combined_text)
            has_explicit_gift = self._has_explicit_gift_json_signal(item)
            if not has_explicit_gift and not (has_text_gift and text_gift_name):
                continue

            props = item.get('basic_props') if isinstance(item.get('basic_props'), dict) else {}
            title = self._short_text(props.get('title') or item.get('title') or item.get('nick_name') or item.get('nickname'))
            desc = self._short_text(props.get('desc') or item.get('desc') or item.get('description') or item.get('content'))
            icon_src = props.get('icon_src') or item.get('icon') or item.get('image') or item.get('avatar') or []
            image_urls = icon_src if isinstance(icon_src, list) else [icon_src] if icon_src else []

            explicit_user_name = self._short_text(
                item.get('user_name') or item.get('userName') or item.get('nickname') or item.get('nick_name')
                or self._first_json_value(item, ('user_name', 'userName', 'nickname', 'nick_name'))
            )
            gift_name = self._short_text(
                item.get('gift_name') or item.get('giftName') or item.get('gift_desc')
                or self._first_json_value(item, ('gift_name', 'giftName', 'gift_desc', 'giftDesc', 'gift_title', 'giftTitle'))
            )
            count = self._first_positive_value(
                item.get('gift_count'), item.get('giftCount'), item.get('count'), item.get('repeat_count'),
                self._first_json_value(item, ('gift_count', 'giftCount', 'repeat_count', 'repeatCount')),
                default=0
            )

            content = desc or title or combined_text
            if not text_gift_name:
                text_user_name, text_gift_name = self._extract_gift_user_from_text(content)
            if not gift_name:
                gift_name = text_gift_name or self._extract_gift_name_from_text(content) or self._extract_gift_name_from_text(combined_text)
            gift_name = self._clean_gift_name(gift_name)
            user_name = explicit_user_name or text_user_name

            if not user_name or not gift_name:
                continue

            count = self._first_positive_value(count, self._extract_gift_count_from_text(content), default=1)

            event = {
                'user_id': str(item.get('user_id') or item.get('userId') or ''),
                'user_name': user_name,
                'gift_id': str(item.get('gift_id') or item.get('giftId') or ''),
                'gift_name': gift_name,
                'gift_count': count,
                'gift_image': [url for url in image_urls if isinstance(url, str) and url.startswith(('http://', 'https://'))],
                'content': content,
            }
            signature = (event['user_id'], event['user_name'], event['gift_id'], event['gift_name'], event['gift_count'])
            existing_event = events_by_signature.get(signature)
            if existing_event is not None:
                if not existing_event['user_id'] and event['user_id']:
                    existing_event['user_id'] = event['user_id']
                if not existing_event['gift_id'] and event['gift_id']:
                    existing_event['gift_id'] = event['gift_id']
                if not existing_event['gift_image'] and event['gift_image']:
                    existing_event['gift_image'] = event['gift_image']
                if len(str(event['content'] or '')) > len(str(existing_event['content'] or '')):
                    existing_event['content'] = event['content']
                continue
            events_by_signature[signature] = event
            events.append(event)
        return events

    def _text_to_plain(self, text):
        if text is None:
            return ''

        pieces = []
        for piece in getattr(text, 'pieces_list', []) or []:
            string_value = getattr(piece, 'string_value', '')
            if string_value:
                pieces.append(string_value)
                continue

            user_value = getattr(piece, 'user_value', None)
            user = getattr(user_value, 'user', None) if user_value else None
            nick_name = getattr(user, 'nick_name', '') if user else ''
            if nick_name:
                pieces.append(nick_name)
                continue

            gift_value = getattr(piece, 'gift_value', None)
            name_ref = getattr(gift_value, 'name_ref', None) if gift_value else None
            gift_name = getattr(name_ref, 'default_pattern', '') if name_ref else ''
            if gift_name:
                pieces.append(gift_name)
                continue

            pattern_ref_value = getattr(piece, 'pattern_ref_value', None)
            pattern_text = getattr(pattern_ref_value, 'default_pattern', '') if pattern_ref_value else ''
            if pattern_text:
                pieces.append(pattern_text)

        return ''.join(pieces) or getattr(text, 'default_patter', '') or ''

    def _extract_chat_gift_event(self, message):
        gift_image = self._first_image_urls(message.gift_image)
        plain_rtf = self._text_to_plain(message.rtf_content)
        candidate_text = ' '.join(
            text.strip() for text in (plain_rtf, message.content)
            if isinstance(text, str) and text.strip()
        )
        has_gift_piece = self._text_has_gift_piece(message.rtf_content)

        if not gift_image and not has_gift_piece:
            return None

        gift_name = (
            self._extract_gift_name_from_text(candidate_text)
            or self._gift_name_from_text_pieces(message.rtf_content)
        )
        gift_name = self._clean_gift_name(gift_name)
        if not gift_name:
            return None

        gift_count = self._first_positive_value(
            self._extract_gift_count_from_text(candidate_text),
            default=1,
        )
        return {
            'user_id': str(message.user.id or ''),
            'user_name': message.user.nick_name or '匿名用户',
            'gift_id': self._gift_id_from_text_pieces(message.rtf_content),
            'gift_name': gift_name,
            'gift_count': gift_count,
            'gift_image': gift_image,
            'content': candidate_text or f"送出了 {gift_name}x{gift_count}",
        }

    @staticmethod
    def _parse_cookie_string(cookie: str) -> dict:
        text = (cookie or '').strip()
        if text.startswith('{'):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict):
                return {str(key): str(value) for key, value in parsed.items() if value is not None}

        cookies = {}
        for item in text.split(';'):
            part = item.strip()
            if not part or '=' not in part:
                continue
            key, value = part.split('=', 1)
            key = key.strip()
            if not key:
                continue
            cookies[key] = value.strip()
        return cookies

    def _get_cookie_value(self, name: str) -> str:
        value = self.session.cookies.get(name)
        if value:
            return value
        return self._parse_cookie_string(self.cookie).get(name, '')

    def _build_cookie_header(self, extra: Optional[dict] = None) -> str:
        cookies = self._parse_cookie_string(self.cookie)
        for key, value in self.session.cookies.get_dict().items():
            cookies[key] = value
        if extra:
            for key, value in extra.items():
                if value:
                    cookies[key] = value
        return '; '.join(f'{key}={value}' for key, value in cookies.items())

    def _get_webcast_did(self) -> str:
        for name in ('webcast_did', 'user_unique_id', 'webcast_user_unique_id'):
            value = self._get_cookie_value(name)
            if value:
                return value
        if not hasattr(self, '_webcast_did'):
            self._webcast_did = str(random.randrange(10 ** 18, 10 ** 19))
        return self._webcast_did

    @property
    def ttwid(self):
        """
        产生请求头部cookie中的ttwid字段，访问抖音网页版直播间首页可以获取到响应cookie中的ttwid
        :return: ttwid
        """
        if self.__ttwid:
            return self.__ttwid
        cookie_ttwid = self._get_cookie_value('ttwid')
        if cookie_ttwid:
            self.__ttwid = cookie_ttwid
            return self.__ttwid
        headers = {
            "User-Agent": self.user_agent,
        }
        if self.cookie:
            headers["Cookie"] = self.cookie
        try:
            response = self.session.get(self.live_url, headers=headers)
            response.raise_for_status()
        except Exception as err:
            self._log("【X】Request the live url error: ", err)
        else:
            self.__ttwid = response.cookies.get('ttwid')
            return self.__ttwid
    
    @property
    def room_id(self):
        """
        根据直播间的地址获取到真正的直播间roomId，有时会有错误，可以重试请求解决
        :return:room_id
        """
        if self.__room_id:
            return self.__room_id
        url = self.live_url + self.live_id
        request_cookie = self._build_cookie_header({
            'ttwid': self.ttwid,
            'msToken': self._get_cookie_value('msToken') or generateMsToken(),
            '__ac_nonce': self._get_cookie_value('__ac_nonce') or '0123407cc00a9e438deb4',
        })
        headers = {
            "User-Agent": self.user_agent,
            "cookie": request_cookie,
        }
        try:
            response = self.session.get(url, headers=headers)
            response.raise_for_status()
        except Exception as err:
            self._log("【X】Request the live room url error: ", err)
        else:
            match = re.search(r'roomId\\":\\"(\d+)\\"', response.text)
            if match is None or len(match.groups()) < 1:
                self._log("【X】No match found for roomId")
            
            self.__room_id = match.group(1)
            
            return self.__room_id
    
    def get_ac_nonce(self):
        """
        获取 __ac_nonce
        """
        existing = self._get_cookie_value("__ac_nonce")
        if existing:
            return existing
        resp_cookies = self.session.get(self.host, headers=self.headers).cookies
        return resp_cookies.get("__ac_nonce")
    
    def get_ac_signature(self, __ac_nonce: str = None) -> str:
        """
        获取 __ac_signature
        """
        __ac_signature = get__ac_signature(self.host[8:], __ac_nonce, self.user_agent)
        self.session.cookies.set("__ac_signature", __ac_signature)
        return __ac_signature
    
    def get_a_bogus(self, url_params: dict):
        """
        获取 a_bogus
        """
        url = urllib.parse.urlencode(url_params)
        ctx = execute_js(self.abogus_file)
        _a_bogus = ctx.call("get_ab", url, self.user_agent)
        return _a_bogus
    
    def get_room_status(self):
        """
        获取直播间开播状态:
        room_status: 2 直播已结束
        room_status: 0 直播进行中
        """
        msToken = self._get_cookie_value('msToken') or generateMsToken()
        nonce = self.get_ac_nonce()
        signature = self.get_ac_signature(nonce)
        url = ('https://live.douyin.com/webcast/room/web/enter/?aid=6383'
               '&app_name=douyin_web&live_id=1&device_platform=web&language=zh-CN&enter_from=page_refresh'
               '&cookie_enabled=true&screen_width=5120&screen_height=1440&browser_language=zh-CN&browser_platform=Win32'
               '&browser_name=Edge&browser_version=140.0.0.0'
               f'&web_rid={self.live_id}'
               f'&room_id_str={self.room_id}'
               '&enter_source=&is_need_double_stream=false&insert_task_id=&live_reason=&msToken=' + msToken)
        query = parse_url(url).query
        params = {i[0]: i[1] for i in [j.split('=') for j in query.split('&')]}
        a_bogus = self.get_a_bogus(params)  # 计算a_bogus,成功率不是100%，出现失败时重试即可
        url += f"&a_bogus={a_bogus}"
        headers = self.headers.copy()
        headers.update({
            'Referer': f'https://live.douyin.com/{self.live_id}',
            'Cookie': self._build_cookie_header({
                'ttwid': self.ttwid,
                '__ac_nonce': nonce,
                '__ac_signature': signature,
                'msToken': msToken,
            }),
        })
        try:
            resp = self.session.get(url, headers=headers, timeout=10)
            payload = resp.json()
        except Exception as err:
            self._log("【X】Get room status error:", err)
            return None

        data = payload.get('data') if isinstance(payload, dict) else None
        if data:
            room_status = data.get('room_status')
            user = data.get('user')
            user_id = user.get('id_str')
            nickname = user.get('nickname')
            status_text = ['正在直播', '已结束'][bool(room_status)]
            self._log(f"【{nickname}】[{user_id}]直播间：{status_text}.")
            self._emit_event(
                'room_status',
                room_status=room_status,
                room_status_text=status_text,
                user_id=user_id,
                nickname=nickname,
                room_id=self.room_id,
                live_id=self.live_id,
            )
            return room_status
        return None
    
    def _connectWebSocket(self):
        """
        连接抖音直播间websocket服务器，请求直播间数据
        """
        now_ms = int(time.time() * 1000)
        user_unique_id = self._get_webcast_did()
        wrds_v = random.randrange(10 ** 18, 10 ** 19)
        cursor = f"d-1_u-1_fh-{wrds_v}_t-{now_ms}_r-1"
        internal_ext = (
            f"internal_src:dim|wss_push_room_id:{self.room_id}|wss_push_did:{user_unique_id}"
            f"|first_req_ms:{now_ms}|fetch_time:{now_ms}|seq:1|wss_info:0-{now_ms}-0-0|"
            f"wrds_v:{wrds_v}"
        )
        wss = ("wss://webcast100-ws-web-hl.douyin.com/webcast/im/push/v2/?app_name=douyin_web"
               "&version_code=180800&webcast_sdk_version=1.0.15"
               "&update_version_code=1.0.15&compress=gzip&device_platform=web&cookie_enabled=true"
               "&screen_width=1536&screen_height=864&browser_language=zh-CN&browser_platform=Win32"
               "&browser_name=Mozilla"
               "&browser_version=5.0%20(Windows%20NT%2010.0;%20Win64;%20x64)%20AppleWebKit/537.36%20(KHTML,"
               "%20like%20Gecko)%20Chrome/126.0.0.0%20Safari/537.36"
               "&browser_online=true&tz_name=Asia/Shanghai"
               f"&cursor={cursor}"
               f"&internal_ext={internal_ext}"
               f"&host=https://live.douyin.com&aid=6383&live_id=1&did_rule=3&endpoint=live_pc&support_wrds=1"
               f"&user_unique_id={user_unique_id}&im_path=/webcast/im/fetch/&identity=audience"
               f"&need_persist_msg_count=15&fetch_rule=1&insert_task_id=&live_reason=&room_id={self.room_id}"
               f"&heartbeatDuration=0")
        
        signature = generateSignature(wss)
        wss += f"&signature={signature}"
        
        headers = {
            "cookie": self._build_cookie_header({
                'ttwid': self.ttwid,
                'msToken': self._get_cookie_value('msToken'),
            }),
            'user-agent': self.user_agent,
        }
        self.ws = websocket.WebSocketApp(wss,
                                         header=headers,
                                         on_open=self._wsOnOpen,
                                         on_message=self._wsOnMessage,
                                         on_error=self._wsOnError,
                                         on_close=self._wsOnClose)
        try:
            self.ws.run_forever()
        except Exception:
            self.stop()
            raise

    def _dispatch_response(self, response, package_log_id=0, ws=None):
        if response.heartbeat_duration:
            self._heartbeat_interval_seconds = max(5.0, response.heartbeat_duration / 1000)

        messages = response.messages_list
        if self.event_handler is not None:
            self._emit_event(
                'packet',
                live_id=self.live_id,
                room_id=self.room_id,
                message_count=len(messages),
                methods=[msg.method for msg in messages],
                heartbeat_duration=response.heartbeat_duration,
            )

        if ws is not None and response.need_ack:
            ack = PushFrame(
                log_id=package_log_id,
                payload_type='ack',
                payload=response.internal_ext.encode('utf-8'),
            ).SerializeToString()
            ws.send(ack, websocket.ABNF.OPCODE_BINARY)

        parsers = self._message_parsers
        for msg in messages:
            method = msg.method
            try:
                parser = parsers.get(method)
                if parser is not None:
                    parser(msg.payload)
                elif self._is_gift_method(method):
                    self._parseGiftMsg(msg.payload, method=method)
                else:
                    self._log(f"【未识别msg】{method} ({len(msg.payload or b'')} bytes)")
                    self._emit_event(
                        'unknown_message',
                        live_id=self.live_id,
                        room_id=self.room_id,
                        method=method,
                        payload_size=len(msg.payload or b''),
                    )
            except Exception as err:
                self._emit_event(
                    'parse_error',
                    live_id=self.live_id,
                    room_id=self.room_id,
                    method=method,
                    message=str(err),
                )

    def _build_fetch_params(self, cursor='', internal_ext='', ms_token=''):
        return {
            'resp_content_type': 'protobuf',
            'did_rule': '3',
            'device_id': '',
            'app_name': 'douyin_web',
            'endpoint': 'live_pc',
            'support_wrds': '1',
            'user_unique_id': self._get_webcast_did(),
            'identity': 'audience',
            'need_persist_msg_count': '15',
            'insert_task_id': '',
            'live_reason': '',
            'room_id': self.room_id,
            'version_code': '180800',
            'live_id': '1',
            'aid': '6383',
            'fetch_rule': '1',
            'cursor': cursor,
            'internal_ext': internal_ext,
            'device_platform': 'web',
            'cookie_enabled': 'true',
            'screen_width': '1536',
            'screen_height': '864',
            'browser_language': 'zh-CN',
            'browser_platform': 'Win32',
            'browser_name': 'Mozilla',
            'browser_version': '5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36',
            'browser_online': 'true',
            'tz_name': 'Asia/Shanghai',
            'msToken': ms_token,
        }

    def _build_fetch_headers(self, ms_token=''):
        headers = self.headers.copy()
        headers.update({
            'Accept': 'application/x-protobuf, application/octet-stream, */*',
            'Referer': f'https://live.douyin.com/{self.live_id}',
            'Cookie': self._build_cookie_header({
                'ttwid': self.ttwid,
                'msToken': ms_token,
            }),
        })
        return headers

    def _fetch_message_response(self, cursor='', internal_ext=''):
        ms_token = self._get_cookie_value('msToken') or generateMsToken()
        params = self._build_fetch_params(cursor=cursor, internal_ext=internal_ext, ms_token=ms_token)
        params['a_bogus'] = self.get_a_bogus(params)
        response = self.session.get(
            'https://live.douyin.com/webcast/im/fetch/',
            params=params,
            headers=self._build_fetch_headers(ms_token=ms_token),
            timeout=20,
        )
        response.raise_for_status()
        return Response().parse(response.content)

    def _connectFetchLoop(self):
        cursor = ''
        internal_ext = ''
        opened = False
        while not self._stop_event.is_set():
            response = self._fetch_message_response(cursor=cursor, internal_ext=internal_ext)
            if not opened:
                opened = True
                self._emit_event(
                    'connection',
                    status='open',
                    live_id=self.live_id,
                    room_id=self.room_id,
                )

            self._dispatch_response(response)
            cursor = response.cursor or cursor
            internal_ext = response.internal_ext or internal_ext

            sleep_seconds = max(0.5, (response.fetch_interval or 1000) / 1000)
            time.sleep(sleep_seconds)
        if opened:
            self._emit_event(
                'connection',
                status='stopped' if self._stop_event.is_set() else 'closed',
                live_id=self.live_id,
                room_id=self.room_id,
            )
    
    def _sendHeartbeat(self):
        """
        发送心跳包
        """
        ws = self.ws
        while not self._stop_event.is_set() and self.ws is ws:
            try:
                if ws is None or ws.sock is None or not ws.sock.connected:
                    break
                heartbeat = PushFrame(payload_type='hb').SerializeToString()
                ws.send(heartbeat, websocket.ABNF.OPCODE_BINARY)
                self._log("【√】发送心跳包")
            except Exception as e:
                self._log("【X】心跳包检测错误: ", e)
                break
            else:
                time.sleep(max(5.0, self._heartbeat_interval_seconds))
    
    def _wsOnOpen(self, ws):
        """
        连接建立成功
        """
        self._log("【√】WebSocket连接成功.")
        self._emit_event('connection', status='open', live_id=self.live_id, room_id=self.room_id)
        self._heartbeat_thread = threading.Thread(target=self._sendHeartbeat, daemon=True)
        self._heartbeat_thread.start()
    
    def _wsOnMessage(self, ws, message):
        """
        接收到数据
        :param ws: websocket实例
        :param message: 数据
        """
        
        # 根据proto结构体解析对象
        package = PushFrame().parse(message)
        response = Response().parse(gzip.decompress(package.payload))
        self._dispatch_response(response, package_log_id=package.log_id, ws=ws)
    
    def _wsOnError(self, ws, error):
        self._log("WebSocket error: ", error)
        if self._stop_event.is_set():
            return
        self._emit_event('connection', status='error', message=str(error), live_id=self.live_id, room_id=self.room_id)
    
    def _wsOnClose(self, ws, *args):
        self._log("WebSocket connection closed.")
        self.ws = None
        self._heartbeat_thread = None
        if self._stop_event.is_set():
            status = 'stopped'
        else:
            status = 'closed'
        self._emit_event(
            'connection',
            status=status,
            message=str(args) if args else '',
            live_id=self.live_id,
            room_id=self.room_id,
        )
    
    def _parseChatMsg(self, payload):
        """聊天消息"""
        message = ChatMessage().parse(payload)
        gift_event = self._extract_chat_gift_event(message)
        if gift_event:
            signature = (
                'WebcastChatMessage',
                gift_event['user_id'],
                str(getattr(message.common, 'log_id', '') or getattr(message.common, 'msg_id', '') or gift_event['gift_id']),
                gift_event['gift_name'],
                gift_event['gift_count'],
            )
            if not self._remember_gift_event(signature):
                return
            self._log(
                f"【礼物chat】{gift_event['user_name']} 送出了 "
                f"{gift_event['gift_name']}x{gift_event['gift_count']}"
            )
            self._emit_event(
                'gift',
                live_id=self.live_id,
                room_id=self.room_id,
                method='WebcastChatMessage',
                user_id=gift_event['user_id'],
                user_name=gift_event['user_name'],
                gift_id=gift_event['gift_id'],
                gift_name=gift_event['gift_name'],
                gift_count=gift_event['gift_count'],
                gift_image=gift_event['gift_image'],
                content=f"送出了 {gift_event['gift_name']}x{gift_event['gift_count']}",
                chat_rtf_text=gift_event['content'],
            )
            return

        user_name = message.user.nick_name
        user_id = message.user.id
        content = message.content or self._text_to_plain(message.rtf_content)
        self._log(f"【聊天msg】[{user_id}]{user_name}: {content}")
        self._emit_event(
            'chat',
            live_id=self.live_id,
            room_id=self.room_id,
            user_id=str(user_id),
            user_name=user_name,
            content=content,
        )
    
    def _parseGiftMsg(self, payload, method='WebcastGiftMessage'):
        """礼物消息"""
        message = GiftMessage().parse(payload)
        raw_message = self._decode_raw_gift_payload(payload)
        user = message.user
        gift = message.gift
        tray_text = self._text_to_plain(message.tray_display_text) or raw_message.get('tray_text') or ''
        _, text_gift_name = self._extract_gift_user_from_text(tray_text)
        user_name = user.nick_name or raw_message.get('user_name') or '匿名用户'
        user_id = user.id or raw_message.get('user_id') or ''
        gift_id = message.gift_id or gift.id or raw_message.get('gift_id') or 0
        gift_name = (gift.name or gift.describe or raw_message.get('gift_name')
                     or text_gift_name or self._extract_gift_name_from_text(tray_text) or f"礼物{gift_id}")
        gift_cnt = self._first_positive_value(message.combo_count, message.repeat_count, message.total_count,
                                              message.group_count, raw_message.get('gift_count'), default=1)
        signature = (method, str(user_id), str(gift_id), gift_name, str(gift_cnt), str(message.trace_id or message.log_id))
        if not self._remember_gift_event(signature):
            return
        self._log(f"【礼物msg】{user_name} 送出了 {gift_name}x{gift_cnt}")
        self._emit_event(
            'gift',
            live_id=self.live_id,
            room_id=self.room_id,
            method=method,
            user_id=str(user_id),
            user_name=user_name,
            gift_id=str(gift_id),
            gift_name=gift_name,
            gift_count=gift_cnt,
            repeat_count=message.repeat_count or raw_message.get('repeat_count'),
            combo_count=message.combo_count or raw_message.get('combo_count'),
            total_count=message.total_count or raw_message.get('total_count'),
            group_count=message.group_count or raw_message.get('group_count'),
            diamond_count=gift.diamond_count or raw_message.get('diamond_count'),
            gift_image=self._first_image_urls(gift.image, gift.icon) or raw_message.get('gift_image'),
            tray_text=raw_message.get('tray_text'),
            content=f"送出了 {gift_name}x{gift_cnt}",
        )

    def _parseInRoomBannerMsg(self, payload):
        """直播间横幅消息，部分新版礼物提示会以 JSON banner 下发。"""
        emitted = 0
        for text in self._extract_banner_json_texts(payload):
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                continue

            for event in self._extract_banner_gift_events(data):
                signature = (
                    'WebcastInRoomBannerMessage',
                    event.get('user_id'),
                    event.get('user_name'),
                    event.get('gift_id'),
                    event.get('gift_name'),
                    event.get('gift_count'),
                    event.get('content'),
                )
                if not self._remember_gift_event(signature):
                    continue

                self._log(f"【礼物banner】{event.get('user_name')} {event.get('content')}")
                self._emit_event(
                    'gift',
                    live_id=self.live_id,
                    room_id=self.room_id,
                    method='WebcastInRoomBannerMessage',
                    user_id=event.get('user_id') or '',
                    user_name=event.get('user_name') or '匿名用户',
                    gift_id=event.get('gift_id') or '',
                    gift_name=event.get('gift_name') or '礼物',
                    gift_count=event.get('gift_count') or 1,
                    gift_image=event.get('gift_image') or [],
                    content=event.get('content') or '',
                )
                emitted += 1

        if emitted == 0:
            self._emit_event(
                'unknown_message',
                live_id=self.live_id,
                room_id=self.room_id,
                method='WebcastInRoomBannerMessage',
                payload_size=len(payload or b''),
            )
    
    def _parseLikeMsg(self, payload):
        '''点赞消息'''
        message = LikeMessage().parse(payload)
        user_name = message.user.nick_name
        user_id = message.user.id
        count = message.count
        self._log(f"【点赞msg】{user_name} 点了{count}个赞")
        self._emit_event(
            'like',
            live_id=self.live_id,
            room_id=self.room_id,
            user_id=str(user_id),
            user_name=user_name,
            count=count,
            total=message.total,
            content=f"点了{count}个赞",
        )

    def _parseMemberMsg(self, payload):
        '''进入直播间消息'''
        message = MemberMessage().parse(payload)
        user_name = message.user.nick_name
        user_id = message.user.id
        gender = {
            0: "unknown",
            1: "male",
            2: "female",
        }.get(message.user.gender, str(message.user.gender))
        self._log(f"【进场msg】[{user_id}][{gender}]{user_name} 进入了直播间")
    
    def _parseSocialMsg(self, payload):
        '''关注消息'''
        message = SocialMessage().parse(payload)
        user_name = message.user.nick_name
        user_id = message.user.id
        self._log(f"【关注msg】[{user_id}]{user_name} 关注了主播")
    
    def _parseRoomUserSeqMsg(self, payload):
        '''直播间统计'''
        message = RoomUserSeqMessage().parse(payload)
        current = message.total
        total = message.total_pv_for_anchor
        self._log(f"【统计msg】当前观看人数: {current}, 累计观看人数: {total}")
    
    def _parseFansclubMsg(self, payload):
        '''粉丝团消息。抖音 Web 会把点亮粉丝团作为礼物动效展示。'''
        message = FansclubMessage().parse(payload)
        content = message.content
        user_name = message.user.nick_name or self._extract_fansclub_user_name(content) or '匿名用户'
        user_id = message.user.id or message.user.id_str or ''
        gift_name = self._fansclub_gift_name(message.type, content)
        self._log(f"【粉丝团msg】 {content}")
        if not gift_name:
            return

        self._emit_event(
            'gift',
            live_id=self.live_id,
            room_id=self.room_id,
            method='WebcastFansclubMessage',
            user_id=str(user_id),
            user_name=user_name,
            gift_id='fansclub',
            gift_name=gift_name,
            gift_count=1,
            content=f"送出了 {gift_name}x1",
            fansclub_content=content,
        )

    @staticmethod
    def _extract_fansclub_user_name(content):
        match = re.search(r'恭喜\s+(.+?)\s+成为第', str(content or ''))
        return match.group(1).strip() if match else ''

    @staticmethod
    def _fansclub_gift_name(message_type, content):
        if message_type == 2 or '成为第' in str(content or ''):
            return '点亮粉丝团'
        if message_type == 1 or '升级' in str(content or ''):
            return '粉丝团升级'
        return ''
    
    def _parseEmojiChatMsg(self, payload):
        '''聊天表情包消息'''
        message = EmojiChatMessage().parse(payload)
        emoji_id = message.emoji_id
        user = message.user
        common = message.common
        default_content = message.default_content
        self._log(f"【聊天表情包id】 {emoji_id},user：{user},common:{common},default_content:{default_content}")
    
    def _parseRoomMsg(self, payload):
        message = RoomMessage().parse(payload)
        common = message.common
        room_id = common.room_id
        self._log(f"【直播间msg】直播间id:{room_id}")
    
    def _parseRoomStatsMsg(self, payload):
        message = RoomStatsMessage().parse(payload)
        display_long = message.display_long
        self._log(f"【直播间统计msg】{display_long}")
    
    def _parseRankMsg(self, payload):
        message = RoomRankMessage().parse(payload)
        ranks_list = message.ranks_list
        self._log(f"【直播间排行榜msg】{ranks_list}")
    
    def _parseControlMsg(self, payload):
        '''直播间状态消息'''
        message = ControlMessage().parse(payload)
        
        if message.status == 3:
            self._log("直播间已结束")
            self._emit_event('room_status', room_status=message.status, room_status_text='已结束', room_id=self.room_id,
                             live_id=self.live_id)
            self.stop()
    
    def _parseRoomStreamAdaptationMsg(self, payload):
        message = RoomStreamAdaptationMessage().parse(payload)
        adaptationType = message.adaptation_type
        self._log(f'直播间adaptation: {adaptationType}')
