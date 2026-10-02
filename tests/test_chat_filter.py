"""聊天内容审核过滤 - 14个测试覆盖模糊匹配/白名单/上下文/申诉/多语言/拼音"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from chat.filter import ChatFilter


class TestFuzzyMatch:
    def test_catches_homophone_and_split(self):
        cf = ChatFilter()
        assert len(cf.check_sensitive_word("白-痴")) > 0
        assert len(cf.check_sensitive_word("白 痴")) > 0

    def test_symbol_insertion_and_homophone(self):
        cf = ChatFilter()
        assert len(cf.check_sensitive_word("白**痴")) > 0
        assert len(cf.check_sensitive_word("百痴")) > 0
        assert "***" in cf.filter_message("你就是个白-痴")


class TestWhitelist:
    def test_normal_words_not_filtered(self):
        cf = ChatFilter()
        cf.whitelist.add("白色")
        result = cf.filter_message("白色装备")
        assert "***" not in result

    def test_whitelist_protects_substring_and_keeps_real_hit(self):
        cf = ChatFilter()
        cf.sensitive_words.add("白")
        cf.whitelist.add("白色")
        assert "***" not in cf.filter_message("白色装备")
        assert "***" in cf.filter_message("白痴")


class TestDynamicLibrary:
    def test_word_library_updates_at_runtime(self):
        cf = ChatFilter()
        cf.add_sensitive_word("菜鸡")
        assert len(cf.check_sensitive_word("你真是个菜鸡")) > 0
        cf.remove_sensitive_word("菜鸡")
        assert len(cf.check_sensitive_word("你真是个菜鸡")) == 0
        cf.update_sensitive_words({"外挂"})
        assert "白痴" not in cf.sensitive_words
        assert len(cf.check_sensitive_word("别用外挂")) > 0


class TestContextAnalysis:
    def test_context_considered(self):
        cf = ChatFilter()
        cf.player_history["p1"] = ["你好", "今天天气不错"]
        result = cf.analyze_context("p1", "你好")
        assert result["risk"] == "low"

    def test_first_offense_warns_repeat_offense_muted(self):
        cf = ChatFilter()
        first = cf.analyze_context("p2", "废物")
        assert first["risk"] == "medium"
        assert first["action"] == "warn"
        assert "p2" not in cf.penalties
        second = cf.analyze_context("p2", "废物")
        assert second["risk"] == "high"
        assert second["action"] == "mute"
        assert cf.penalties["p2"]["muted"] is True


class TestAppealEvidence:
    def test_appeal_checks_original_message(self):
        cf = ChatFilter()
        assert cf.handle_appeal("p1", "我只是说了正常的话") is False

    def test_false_positive_appeal_approved_and_unmuted(self):
        cf = ChatFilter()
        cf.sensitive_words.add("白")
        cf.whitelist.add("白色")
        cf.analyze_context("p9", "白色装备")
        cf.penalties["p9"] = {"muted": True, "paused": False, "permanent": False}
        assert cf.handle_appeal("p9", "我说的是白色装备，游戏正常术语") is True
        assert "p9" not in cf.violations
        assert "p9" not in cf.penalties

    def test_appeal_fast_track_pauses_penalty(self):
        cf = ChatFilter()
        cf.analyze_context("p3", "废物")
        cf.analyze_context("p3", "废物")
        assert cf.penalties["p3"]["muted"] is True
        cf.submit_appeal("p3", "我被误封了")
        assert cf.penalties["p3"]["paused"] is True
        assert cf.appeals["p3"]["status"] == "pending"


class TestMultilingual:
    def test_english_slang_detected(self):
        cf = ChatFilter()
        cf.sensitive_words.add("damn")
        assert len(cf.filter_multilingual("damn it")) > 0

    def test_japanese_korean_builtin_detected(self):
        cf = ChatFilter()
        assert len(cf.filter_multilingual("お前はバカだ")) > 0
        assert len(cf.filter_multilingual("씨발")) > 0
        assert len(cf.filter_multilingual("what the fuck")) > 0


class TestPinyinAbbreviation:
    def test_pinyin_abbreviation_detected(self):
        cf = ChatFilter()
        cf.sensitive_words.add("woc")
        assert len(cf.check_sensitive_word("woc")) > 0

    def test_builtin_pinyin_abbreviation_detected(self):
        cf = ChatFilter()
        assert len(cf.check_sensitive_word("nmsl")) > 0
        assert len(cf.check_sensitive_word("woc 这也行")) > 0
        assert len(cf.check_sensitive_word("usb device")) == 0
