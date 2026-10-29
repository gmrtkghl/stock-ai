import unittest
import cloud_analysis as ca

class CloudAnalysisTests(unittest.TestCase):
    def sample(self):
        return {
            "market": {
                "domestic": {"keywords": [{"keyword":"AI·반도체","count":3,"item_ids":["M1"]}], "items": [{"id":"M1","title":"반도체 수출 증가"}]},
                "overseas": {"keywords": [{"keyword":"금리·중앙은행","count":4,"item_ids":["M2"]}], "items": [{"id":"M2","title":"Fed rate decision"}]},
            },
            "stocks": [{
                "symbol":"NVDA",
                "quote":{"change_pct":2.4},
                "analysis":{"return_20d_pct":8.2,"sma20":120,"sma60":110,"rsi14":65},
                "position":None,
                "news":{"items":[{"id":"S1","title":"Nvidia gains on strong AI demand"}]},
            }],
        }

    def test_dashboard_shape(self):
        result, warning = ca.generate_dashboard_brief(self.sample())
        self.assertIsInstance(result, dict)
        self.assertIn(result["recommendations"][0]["stance"], {"매수 검토","보유 검토","매도 검토","관망"})
        self.assertTrue(warning)
        self.assertIn("overseas_to_korea", result["cross_market_impact"])

    def test_stock_explanation(self):
        snap = self.sample()["stocks"][0]
        answer, warning = ca.explain_snapshot(snap, "왜?")
        self.assertIn("근거", answer)
        self.assertTrue(warning)

if __name__ == '__main__':
    unittest.main()
