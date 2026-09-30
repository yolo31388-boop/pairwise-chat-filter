"""聊天内容审核过滤 - 红态测试"""
import pytest, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from chat.filter import ChatFilter

class TestFuzzyMatch:
    def test_catches_homophone_and_split(self):
        cf = ChatFilter()
        assert len(cf.check_sensitive_word("白-痴")) > 0
        assert len(cf.check_sensitive_word("白 痴")) > 0

class TestWhitelist:
    def test_normal_words_not_filtered(self):
        cf = ChatFilter()
        cf.whitelist.add("白色")
        result = cf.filter_message("白色装备")
        assert "***" not in result

class TestContextAnalysis:
    def test_context_considered(self):
        cf = ChatFilter()
        cf.player_history["p1"] = ["你好", "今天天气不错"]
        result = cf.analyze_context("p1", "你好")
        assert result["risk"] == "low"

class TestAppealEvidence:
    def test_appeal_checks_original_message(self):
        cf = ChatFilter()
        assert cf.handle_appeal("p1", "我只是说了正常的话") == False

class TestMultilingual:
    def test_english_slang_detected(self):
        cf = ChatFilter()
        cf.sensitive_words.add("damn")
        assert len(cf.filter_multilingual("damn it")) > 0

class TestPinyinAbbreviation:
    def test_pinyin_abbreviation_detected(self):
        cf = ChatFilter()
        cf.sensitive_words.add("woc")
        assert len(cf.check_sensitive_word("woc")) > 0
