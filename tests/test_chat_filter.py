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


class TestFuzzyMatchExtra:
    def test_homophone_and_leet(self):
        cf = ChatFilter()
        assert len(cf.check_sensitive_word("白吃")) > 0       # 谐音
        assert len(cf.check_sensitive_word("d4mn")) > 0       # leet 变形

    def test_symbol_insertion_filtered(self):
        cf = ChatFilter()
        assert cf.filter_message("你是白-痴") == "你是***"


class TestDynamicWordBank:
    def test_add_and_remove_word(self):
        cf = ChatFilter()
        cf.add_word("新骂法")
        assert len(cf.check_sensitive_word("新-骂-法")) > 0
        cf.remove_word("新骂法")
        assert len(cf.check_sensitive_word("新骂法")) == 0


class TestWhitelistExtra:
    def test_whitelisted_substring_not_filtered(self):
        cf = ChatFilter()
        cf.add_word("白")
        cf.whitelist.add("白色")
        assert "***" not in cf.filter_message("白色装备")
        assert cf.filter_message("你真白") == "你真***"


class TestEscalatingPenalty:
    def test_first_offense_warned_not_banned(self):
        cf = ChatFilter()
        result = cf.moderate("p1", "你这个白痴")
        assert result["recommended_action"] == "warn"
        assert not cf.is_muted("p1")

    def test_repeat_offender_muted(self):
        cf = ChatFilter()
        cf.moderate("p1", "白痴")
        cf.moderate("p1", "又骂人白痴")
        assert cf.is_muted("p1")


class TestAppealFlow:
    def test_no_record_appeal_rejected(self):
        cf = ChatFilter()
        assert cf.handle_appeal("p1", "写得很好" * 20) == False

    def test_false_positive_fast_track_approved(self):
        cf = ChatFilter()
        cf.whitelist.add("基层")
        cf.violations["p1"] = {"message": "基层工作汇报", "hits": ["基"]}
        cf.punishments["p1"] = {"muted_until": __import__("datetime").datetime.max,
                                "suspended": False}
        assert cf.handle_appeal("p1", "我是正常用语") == True
        assert not cf.is_muted("p1")

    def test_punishment_suspended_during_appeal(self):
        cf = ChatFilter()
        cf.moderate("p1", "白痴")
        cf.moderate("p1", "白痴")
        assert cf.is_muted("p1")
        assert cf.handle_appeal("p1", "我不服") == False
        assert not cf.is_muted("p1")


class TestMultilingualExtra:
    def test_japanese_korean_detected(self):
        cf = ChatFilter()
        assert len(cf.filter_multilingual("ばかじゃないの")) > 0
        assert len(cf.filter_multilingual("바보야")) > 0

    def test_builtin_pinyin_abbreviations(self):
        cf = ChatFilter()
        assert len(cf.check_sensitive_word("nmsl")) > 0
