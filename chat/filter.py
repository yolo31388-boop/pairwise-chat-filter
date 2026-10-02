"""聊天内容审核过滤。

能力：
- 模糊匹配：谐音/拆字/符号插入绕过检测
- 敏感词库动态更新
- 白名单 + 上下文排除误判
- 上下文分析结合玩家历史记录，分级处罚
- 申诉复核原始消息，申诉期间暂停处罚（快速通道）
- 多语言（中/英/日/韩）+ 拼音缩写检测
"""
import re

# 常见谐音/形近字，用于模糊匹配
HOMOPHONES = {
    "白": "百柏",
    "痴": "吃嗤",
    "笨": "苯",
    "蛋": "旦淡弹",
    "废": "费肺",
    "物": "务雾",
    "傻": "沙",
    "逼": "比笔",
    "草": "操",
    "妈": "马麻",
    "死": "司思",
    "贱": "见剑",
}

# 字符之间允许插入的任意符号/空白（拆字、符号插入）
_SEP = r"[^\w]*"

# 内置多语言敏感词
MULTILINGUAL_WORDS = {
    "en": {"damn", "fuck", "shit", "bitch", "bastard"},
    "ja": {"バカ", "馬鹿", "アホ", "くそ", "クソ"},
    "ko": {"씨발", "병신", "개새끼"},
}

# 拼音缩写骂人话
PINYIN_ABBREVIATIONS = {"woc", "nmsl", "cnm", "tmd", "wdnmd", "sb"}


class ChatFilter:
    def __init__(self):
        self.sensitive_words = {"白痴", "笨蛋", "废物"}
        self.whitelist = set()
        self.player_history: dict[str, list] = {}
        self.multilingual_words = {lang: set(words) for lang, words in MULTILINGUAL_WORDS.items()}
        self.pinyin_abbreviations = set(PINYIN_ABBREVIATIONS)
        self.violations: dict[str, list] = {}   # pid -> [{message, matches}]
        self.penalties: dict[str, dict] = {}    # pid -> {"muted": bool, "paused": bool}
        self.appeals: dict[str, dict] = {}      # pid -> {"reason": str, "status": str}
        self._patterns: dict[str, re.Pattern] = {}

    # ---------- 词库 ----------

    def add_sensitive_word(self, word: str) -> None:
        self.sensitive_words.add(word)

    def remove_sensitive_word(self, word: str) -> None:
        self.sensitive_words.discard(word)

    def update_sensitive_words(self, words) -> None:
        """动态替换整个敏感词库（如从运营后台热更新）。"""
        self.sensitive_words = set(words)

    def add_multilingual_word(self, lang: str, word: str) -> None:
        self.multilingual_words.setdefault(lang, set()).add(word)

    def _all_words(self) -> set:
        words = set(self.sensitive_words) | set(self.pinyin_abbreviations)
        for lang_words in self.multilingual_words.values():
            words |= lang_words
        return words

    # ---------- 模糊匹配 ----------

    def _pattern_for(self, word: str) -> re.Pattern:
        if word not in self._patterns:
            parts = []
            for ch in word:
                group = ch + HOMOPHONES.get(ch, "")
                parts.append(f"[{re.escape(group)}]" if len(group) > 1 else re.escape(ch))
            body = _SEP.join(parts)
            if word.isascii() and word.isalpha():
                # 纯拉丁词要求整词边界，避免 "usb" 误中 "sb"
                body = rf"(?<![0-9A-Za-z]){body}(?![0-9A-Za-z])"
            self._patterns[word] = re.compile(body, re.IGNORECASE)
        return self._patterns[word]

    def _match_spans(self, message: str) -> list:
        spans = []
        for word in self._all_words():
            for m in self._pattern_for(word).finditer(message):
                spans.append(m.span())
        return spans

    def _whitelisted_spans(self, message: str) -> list:
        spans = []
        for phrase in self.whitelist:
            start = 0
            while True:
                idx = message.find(phrase, start)
                if idx < 0:
                    break
                spans.append((idx, idx + len(phrase)))
                start = idx + 1
        return spans

    @staticmethod
    def _overlaps(span_a, span_b) -> bool:
        return span_a[0] < span_b[1] and span_b[0] < span_a[1]

    def _unprotected_spans(self, message: str) -> list:
        protected = self._whitelisted_spans(message)
        return [s for s in self._match_spans(message)
                if not any(self._overlaps(s, p) for p in protected)]

    def check_sensitive_word(self, message: str) -> list:
        """模糊匹配：谐音、拆字、符号插入、多语言、拼音缩写。"""
        return [word for word in self._all_words()
                if self._pattern_for(word).search(message)]

    def filter_message(self, message: str) -> str:
        """掩码命中片段；白名单覆盖的片段不过滤（如“白色装备”）。"""
        spans = self._unprotected_spans(message)
        if not spans:
            return message
        spans.sort()
        merged = []
        for span in spans:
            if merged and span[0] <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], span[1]))
            else:
                merged.append(span)
        out, pos = [], 0
        for start, end in merged:
            out.append(message[pos:start])
            out.append("***")
            pos = end
        out.append(message[pos:])
        return "".join(out)

    # ---------- 上下文分析 ----------

    def analyze_context(self, pid: str, message: str) -> dict:
        """结合历史记录分级：初犯警告，屡犯才禁言（非永久）。"""
        history = self.player_history.setdefault(pid, [])
        past_violations = sum(1 for m in history if self.check_sensitive_word(m))
        history.append(message)

        matches = self.check_sensitive_word(message)
        if not matches:
            return {"risk": "low", "action": "none", "matches": [],
                    "history_violations": past_violations}

        self.violations.setdefault(pid, []).append(
            {"message": message, "matches": matches})

        if past_violations == 0:
            return {"risk": "medium", "action": "warn", "matches": matches,
                    "history_violations": past_violations}
        self.penalties[pid] = {"muted": True, "paused": False, "permanent": False}
        return {"risk": "high", "action": "mute", "matches": matches,
                "history_violations": past_violations}

    # ---------- 申诉 ----------

    def submit_appeal(self, pid: str, reason: str) -> None:
        """快速通道：提交申诉即暂停处罚，等待复核。"""
        self.appeals[pid] = {"reason": reason, "status": "pending"}
        penalty = self.penalties.get(pid)
        if penalty:
            penalty["paused"] = True

    def _is_false_positive(self, message: str) -> bool:
        spans = self._match_spans(message)
        if not spans:
            return True
        protected = self._whitelisted_spans(message)
        return all(any(self._overlaps(s, p) for p in protected) for s in spans)

    def handle_appeal(self, pid: str, reason: str) -> bool:
        """复核原始消息与上下文（而非只看申诉文本）；申诉期间暂停处罚。"""
        self.submit_appeal(pid, reason)
        records = self.violations.get(pid)
        if not records:
            self.appeals[pid]["status"] = "rejected"
            return False
        original = records[-1]["message"]
        if self._is_false_positive(original):
            # 误判：撤销违规记录并解除处罚
            self.violations.pop(pid, None)
            self.penalties.pop(pid, None)
            self.appeals[pid]["status"] = "approved"
            return True
        # 复核确认违规：恢复处罚
        penalty = self.penalties.get(pid)
        if penalty:
            penalty["paused"] = False
        self.appeals[pid]["status"] = "rejected"
        return False

    # ---------- 多语言 ----------

    def filter_multilingual(self, message: str) -> list:
        """中/英/日/韩敏感词 + 拼音缩写检测。"""
        return self.check_sensitive_word(message)
