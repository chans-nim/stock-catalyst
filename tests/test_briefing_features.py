import unittest
from unittest.mock import Mock, patch

from stock_catalyst import briefing, english_learning
from stock_catalyst.collectors import global_markets


class GlobalMarketsTest(unittest.TestCase):
    @patch("stock_catalyst.collectors.global_markets.requests.get")
    def test_fetch_index_calculates_change_rate(self, get):
        response = Mock()
        response.json.return_value = {
            "chart": {"result": [{
                "timestamp": [1787702400, 1787788800],
                "indicators": {"quote": [{"close": [100.0, 102.5]}]},
            }]}
        }
        get.return_value = response

        result = global_markets.fetch_index("^TEST", "테스트")

        self.assertEqual(result["price"], 102.5)
        self.assertAlmostEqual(result["change_rate"], 2.5)
        response.raise_for_status.assert_called_once()

    @patch("stock_catalyst.collectors.global_markets.fetch_index")
    def test_one_market_failure_does_not_stop_others(self, fetch):
        fetch.side_effect = [
            {"symbol": "A", "name": "A", "price": 1, "change_rate": 0, "market_date": "08/27"},
            RuntimeError("temporary failure"),
        ]
        result = global_markets.fetch_markets([
            {"symbol": "A", "name": "A"},
            {"symbol": "B", "name": "B"},
        ])
        self.assertEqual(len(result), 2)
        self.assertIn("error", result[1])


class BriefingTest(unittest.TestCase):
    def test_change_icons_use_korean_market_colors(self):
        self.assertEqual(briefing._change_icon(1), "🔴▲")
        self.assertEqual(briefing._change_icon(-1), "🔵▼")
        self.assertEqual(briefing._change_icon(0), "⚪─")

    @patch("stock_catalyst.briefing.kis.fetch_watchlist", return_value=[])
    @patch("stock_catalyst.briefing.global_markets.fetch_markets")
    @patch("stock_catalyst.briefing.db.recent_items", return_value=[])
    def test_build_renders_market_and_futures_sections(self, recent, fetch, watchlist):
        fetch.side_effect = [
            [{"name": "S&P 500", "price": 7000, "change_rate": -0.5, "market_date": "08/26"}],
            [{"name": "나스닥 100 선물", "price": 25000, "change_rate": 0.75, "market_date": "08/27"}],
        ]

        text = briefing.build(Mock())

        self.assertIn("🌎 해외증시", text)
        self.assertIn("📈 미국 지수 선물", text)
        self.assertIn("🔵▼0.50%", text)
        self.assertIn("🔴▲0.75%", text)


class EnglishLearningTest(unittest.TestCase):
    SAMPLE = """
    <div class="word_card" id="word_card">
      <button data-sentence="hatch" data-pron="hætʃ" data-pronFile="/hatch.mp3"></button>
      <span class="part">동사</span><span class="mean_text">부화하다</span>
      <div class="example" lang="en">Ten chicks <strong>hatch</strong> today.</div>
      <div class="example_mean" lang="ko">병아리 열 마리가 오늘 부화한다.</div>
    </div>
    """

    def test_parse_word_with_example(self):
        words = english_learning.parse_words(self.SAMPLE)
        self.assertEqual(len(words), 1)
        self.assertEqual(words[0]["word"], "hatch")
        self.assertEqual(words[0]["meaning"], "부화하다")
        self.assertEqual(words[0]["pronunciation_file"], "/hatch.mp3")
        self.assertEqual(words[0]["example"], "Ten chicks hatch today.")
        self.assertEqual(words[0]["example_mean"], "병아리 열 마리가 오늘 부화한다.")

    def test_tts_url_contains_encoded_sentence(self):
        url = english_learning._tts_url("Listen to this example.")
        self.assertIn("speech_fmt=mp3", url)
        self.assertIn("Listen+to+this+example.", url)


if __name__ == "__main__":
    unittest.main()
