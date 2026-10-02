"""聊天内容审核过滤。

- 模糊匹配：符号插入 / 空格拆字 / 谐音变体 / leet 变形
- 敏感词库动态更新（内存增删 + 文件热加载）
- 白名单 + 上下文排除误判
- 结合玩家历史记录的上下文风险分析与阶梯处罚
- 申诉快速通道，申诉期间暂停处罚
- 多语言（中/英/日/韩）与拼音缩写检测
"""
from __future__ import annotations

import os
import unicodedata
from datetime import datetime, timedelta


class ChatFilter:
    # 内置多语言敏感词
    DEFAULT_WORDS = {
        "白痴", "笨蛋", "废物",                      # 中文
        "fuck", "shit", "bitch", "damn",             # 英文
        "ばか", "馬鹿", "くそ",                       # 日文
        "바보", "병신", "씨발",                        # 韩文
    }
    # 拼音缩写
    PINYIN_ABBREV = {"woc", "nmsl", "tmd", "mdzz"}
    # 谐音变体表（可按词扩展）
    HOMOPHONES = {
        "白痴": ["白吃", "白迟", "白池", "白齿"],
        "笨蛋": ["笨旦", "笨弹"],
        "废物": ["费物", "废务"],
    }
    # leet 变形还原（数字伪装成字母）
    LEET_TABLE = str.maketrans({"4": "a", "3": "e", "1": "i", "0": "o",
                                "5": "s", "7": "t", "8": "b"})
    # 阶梯处罚：警告 -> 10分钟 -> 1小时 -> 1天（不再首次即永封）
    MUTE_SCHEDULE = [timedelta(minutes=10), timedelta(hours=1), timedelta(days=1)]

    def __init__(self, word_file: str | None = None):
        self.sensitive_words = set(self.DEFAULT_WORDS) | self.PINYIN_ABBREV
        self.whitelist: set[str] = set()
        self.player_history: dict[str, list[str]] = {}
        self.homophones = {w: list(v) for w, v in self.HOMOPHONES.items()}
        self.word_file = word_file
        if word_file:
            self.reload_words()
        self.offense_counts: dict[str, int] = {}
        self.violations: dict[str, dict] = {}
        self.punishments: dict[str, dict] = {}
        self.appeals: dict[str, dict] = {}

    # ---------- 动态词库 ----------

    def add_word(self, word: str) -> None:
        self.sensitive_words.add(word)

    def remove_word(self, word: str) -> None:
        self.sensitive_words.discard(word)

    def load_words(self, words) -> None:
        self.sensitive_words.update(w.strip() for w in words if w.strip())

    def reload_words(self) -> None:
        """从文件热加载敏感词（每行一个，# 开头为注释）。"""
        if not self.word_file or not os.path.exists(self.word_file):
            return
        with open(self.word_file, encoding="utf-8") as f:
            self.load_words(line for line in f if not line.startswith("#"))

    def add_homophone(self, word: str, variant: str) -> None:
        self.homophones.setdefault(word, []).append(variant)

    # ---------- 归一化与模糊匹配 ----------

    @staticmethod
    def _normalize_with_map(text: str):
        """NFKC 归一 + 小写 + 去除符号/空格，返回 (归一化串, 归一化下标->原串下标)。"""
        chars, index_map = [], []
        for i, ch in enumerate(text):
            for c in unicodedata.normalize("NFKC", ch):
                c = c.lower()
                if c.isalnum():  # 保留中日韩文字、字母、数字，剔除插入的符号
                    chars.append(c)
                    index_map.append(i)
        return "".join(chars), index_map

    def _variants(self, word: str) -> list[str]:
        return [word, *self.homophones.get(word, [])]

    def _find_spans(self, message: str):
        """在归一化文本中定位命中区间（含谐音、leet 变形），并做白名单豁免。"""
        norm, index_map = self._normalize_with_map(message)
        leet = norm.translate(self.LEET_TABLE)
        spans = []
        for word in self.sensitive_words:
            for variant in self._variants(word):
                vn, _ = self._normalize_with_map(variant)
                if not vn:
                    continue
                for hay in (norm, leet):
                    start = hay.find(vn)
                    while start != -1:
                        spans.append((start, start + len(vn), word))
                        start = hay.find(vn, start + 1)
        # 白名单：命中区间完全落在白名单词区间内则豁免
        wl_spans = []
        for word in self.whitelist:
            wn, _ = self._normalize_with_map(word)
            if not wn:
                continue
            start = norm.find(wn)
            while start != -1:
                wl_spans.append((start, start + len(wn)))
                start = norm.find(wn, start + 1)
        kept, seen = [], set()
        for s, e, w in spans:
            if any(ws <= s and e <= we for ws, we in wl_spans):
                continue
            if (s, e) not in seen:
                seen.add((s, e))
                kept.append((s, e, w))
        return kept, index_map

    def check_sensitive_word(self, message: str) -> list:
        if not message:
            return []
        spans, _ = self._find_spans(message)
        return sorted({w for _, _, w in spans})

    def filter_message(self, message: str) -> str:
        if not message:
            return message
        spans, index_map = self._find_spans(message)
        if not spans:
            return message
        # 归一化区间 -> 原串区间，合并重叠后从右往左替换
        ranges = sorted(
            (index_map[s], index_map[e - 1] + 1) for s, e, _ in spans
        )
        merged = []
        for start, end in ranges:
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        for start, end in reversed(merged):
            message = message[:start] + "***" + message[end:]
        return message

    # ---------- 上下文分析 ----------

    def analyze_context(self, pid: str, message: str) -> dict:
        hits = self.check_sensitive_word(message)
        history = self.player_history.get(pid, [])
        history_flags = sum(len(self.check_sensitive_word(m)) for m in history)
        prior_offenses = self.offense_counts.get(pid, 0)
        if not hits:
            risk, action = "low", "none"
        elif prior_offenses == 0 and history_flags == 0:
            risk, action = "medium", "warn"   # 初犯警告，不直接禁言
        else:
            risk, action = "high", "mute"     # 累犯升级处罚
        return {
            "risk": risk,
            "hits": hits,
            "prior_offenses": prior_offenses,
            "history_flags": history_flags,
            "recommended_action": action,
        }

    def moderate(self, pid: str, message: str) -> dict:
        """完整审核流水线：过滤 + 历史记录 + 阶梯处罚。"""
        ctx = self.analyze_context(pid, message)
        filtered = self.filter_message(message)
        self.player_history.setdefault(pid, []).append(message)
        if ctx["hits"]:
            self.offense_counts[pid] = self.offense_counts.get(pid, 0) + 1
            self.violations[pid] = {"message": message, "hits": ctx["hits"],
                                    "time": datetime.now()}
            if ctx["recommended_action"] == "mute":
                step = min(self.offense_counts[pid] - 2, len(self.MUTE_SCHEDULE) - 1)
                self.punishments[pid] = {
                    "muted_until": datetime.now() + self.MUTE_SCHEDULE[max(step, 0)],
                    "suspended": False,
                }
        return {"filtered": filtered, **ctx}

    def is_muted(self, pid: str) -> bool:
        p = self.punishments.get(pid)
        if not p or p.get("suspended"):
            return False
        return p["muted_until"] > datetime.now()

    # ---------- 申诉 ----------

    def handle_appeal(self, pid: str, reason: str) -> bool:
        """申诉处理：核查原始消息与上下文，申诉期间暂停处罚。

        快速通道：原始消息经白名单/上下文复核无命中 -> 立即解封。
        """
        record = self.violations.get(pid)
        if record is None:
            return False  # 无违规记录，申诉无效
        punishment = self.punishments.get(pid)
        if punishment:
            punishment["suspended"] = True  # 申诉期间暂停禁言
        original = record["message"]
        if not self.check_sensitive_word(original):
            self.punishments.pop(pid, None)
            self.violations.pop(pid, None)
            self.appeals[pid] = {"status": "approved", "fast_track": True,
                                 "reason": reason}
            return True
        self.appeals[pid] = {"status": "pending_review", "fast_track": False,
                             "reason": reason, "evidence": record}
        return False

    # ---------- 多语言 ----------

    @staticmethod
    def detect_languages(text: str) -> set:
        langs = set()
        for ch in text:
            cp = ord(ch)
            if 0x4E00 <= cp <= 0x9FFF:
                langs.add("zh")
            elif 0x3040 <= cp <= 0x30FF:
                langs.add("ja")
            elif 0xAC00 <= cp <= 0xD7AF or 0x1100 <= cp <= 0x11FF:
                langs.add("ko")
            elif ch.isascii() and ch.isalpha():
                langs.add("en")
        return langs

    def filter_multilingual(self, message: str) -> list:
        """多语言（中/英/日/韩）+ 拼音缩写检测，返回命中的敏感词。"""
        return self.check_sensitive_word(message)
