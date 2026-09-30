"""聊天内容审核过滤 - 含5个bug"""
import re

class ChatFilter:
    def __init__(self):
        self.sensitive_words = {"白痴", "笨蛋", "废物"}  # bug1: 静态词库
        self.whitelist = set()  # bug2: 无白名单
        self.player_history: dict[str, list] = {}  # bug3: 不用于上下文

    def check_sensitive_word(self, message: str) -> list:
        # bug1: 精确匹配，可绕过
        found = []
        for word in self.sensitive_words:
            if word in message:
                found.append(word)
        return found

    def filter_message(self, message: str) -> str:
        # bug2: 误判正常消息
        for word in self.sensitive_words:
            message = message.replace(word, "***")
        return message

    def analyze_context(self, pid: str, message: str) -> dict:
        # bug3: 不分析上下文
        return {"risk": "high" if self.check_sensitive_word(message) else "low"}

    def handle_appeal(self, pid: str, reason: str) -> bool:
        # bug4: 只看文本不看原始消息
        return len(reason) > 50

    def filter_multilingual(self, message: str) -> list:
        # bug5: 只支持中文
        return self.check_sensitive_word(message)
