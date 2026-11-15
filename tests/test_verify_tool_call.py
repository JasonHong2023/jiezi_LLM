"""工具呼叫驗證器測試：依 ACEBench normal 規則手寫的案例；確認回答內容永不執行。
Tool-call verifier tests: hand-written cases following the ACEBench normal rules; response content never runs."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jiezi.verify import tool_call  # noqa: E402

FUNCS = [
    {"name": "book_hotel", "description": "訂房",
     "parameters": {"type": "object", "required": ["city", "nights"], "properties": {
         "city": {"type": "string"}, "nights": {"type": "integer"}, "breakfast": {"type": "boolean"},
         "guests": {"type": "array", "items": {"type": "string"}},
         "prefs": {"type": "object", "properties": {"floor": {"type": "string"}}},
         "budget": {"type": "float"}}}},
    {"name": "get_weather", "description": "天氣",
     "parameters": {"type": "object", "required": ["city"], "properties": {"city": {"type": "string"}}}},
    {"name": "distractor", "description": "干擾", "arguments": {"type": "object", "properties": {}}},
]


def item(gt):
    return {"data": {"functions": FUNCS, "ground_truth": gt}}


GT = {"book_hotel": {"city": "台北", "nights": 2}}


class TestParse(unittest.TestCase):
    def test_outer_brackets_and_text_around(self):
        calls = tool_call.parse_calls("好的：[book_hotel(city='台北', nights=2)] 完成")
        self.assertEqual(calls, [{"book_hotel": {"city": "台北", "nights": 2}}])

    def test_names_become_strings_and_calls_are_not_run(self):
        calls = tool_call.parse_calls("[f(a=os, b=__import__('os'), c=x.y())]")
        self.assertEqual(calls, [{"f": {"a": "os", "b": {"__import__": {}}, "c": {"x.y": {}}}}])

    def test_numeric_arithmetic_only(self):
        self.assertEqual(tool_call.parse_calls("[f(a=2*3+1, b=-4)]"), [{"f": {"a": 7, "b": -4}}])
        for bad in ("[f(a=x+1)]", "[f(a='a'*10**9)]", "[f(a=lambda: 1)]", "[f(a=2**64)]", "[f(a=1/0)]",
                    "[f(a=" + "[" * 5000 + "]" * 5000 + ")]"):
            with self.assertRaises(tool_call.Unparsed, msg=bad):
                tool_call.parse_calls(bad)

    def test_unparseable_shapes(self):
        for bad in ("沒有呼叫", "[book_hotel(city='台北'", "[1, 2]", "[book_hotel(city=)]"):
            with self.assertRaises(tool_call.Unparsed, msg=bad):
                tool_call.parse_calls(bad)


class TestVerify(unittest.TestCase):
    def check(self, response, gt=GT):
        return tool_call.verify(item(gt), response)

    def test_correct(self):
        r = self.check("[book_hotel(city='台北', nights=2)]")
        self.assertEqual((r["status"], r["score"]), ("correct", 1))

    def test_string_is_normalized_substring(self):
        # 官方：標準化後「答案包含於回答」即可 / upstream: standardized answer contained in the response
        self.assertEqual(self.check("[book_hotel(city='台北市', nights=2)]")["score"], 1)
        gt = {"get_weather": {"city": "New York"}}
        self.assertEqual(self.check("[get_weather(city='new-york')]", gt)["score"], 1)

    def test_wrong_value_and_type(self):
        self.assertEqual(self.check("[book_hotel(city='高雄', nights=2)]")["details"]["error_type"],
                         "value_error:string")
        self.assertEqual(self.check("[book_hotel(city='台北', nights='2')]")["details"]["error_type"], "type_error")

    def test_missing_required_and_extra_param(self):
        self.assertEqual(self.check("[book_hotel(city='台北')]")["details"]["error_type"], "lack_args")
        self.assertEqual(self.check("[book_hotel(city='台北', nights=2, breakfast=True)]")["details"]["error_type"],
                         "addition_args")

    def test_function_count_and_name(self):
        self.assertEqual(self.check("[get_weather(city='台北')]")["details"]["error_type"], "function_mismatch")
        self.assertEqual(self.check("[book_hotel(city='台北', nights=2), get_weather(city='台北')]")
                         ["details"]["error_type"], "wrong functions number")

    def test_parallel_any_order_and_suffixes(self):
        gt = {"get_weather_1": {"city": "台北"}, "get_weather_2": {"city": "東京"}}
        self.assertEqual(self.check("[get_weather(city='東京'), get_weather(city='台北')]", gt)["score"], 1)

    def test_float_accepts_int_and_bool_strings(self):
        gt = {"book_hotel": {"city": "台北", "nights": 1, "budget": 3000.0, "breakfast": True}}
        r = self.check("[book_hotel(city='台北', nights=1, budget=3000, breakfast='true')]", gt)
        self.assertEqual(r["score"], 1)

    def test_list_and_dict(self):
        gt = {"book_hotel": {"city": "台北", "nights": 1, "guests": ["Amy", "Bob"], "prefs": {"floor": "high"}}}
        ok = "[book_hotel(city='台北', nights=1, guests=['amy', 'bob'], prefs={'floor': 'High'})]"
        self.assertEqual(self.check(ok, gt)["score"], 1)
        self.assertEqual(self.check(ok.replace("'bob'", "'carl'"), gt)["details"]["error_type"],
                         "value_error:list/tuple")
        self.assertEqual(self.check(ok.replace("'High'", "'low'"), gt)["details"]["error_type"], "value_error")

    def test_alternative_ground_truths(self):
        gt = [{"get_weather": {"city": "台北"}}, {"get_weather": {"city": "Taipei"}}]
        self.assertEqual(self.check("[get_weather(city='taipei')]", gt)["score"], 1)

    def test_unknown_type_is_wrong_not_crash(self):
        funcs = [{"name": "f", "parameters": {"type": "object", "required": [],
                                              "properties": {"a": {"type": "weird"}}}}]
        r = tool_call.verify({"data": {"functions": funcs, "ground_truth": {"f": {"a": 1}}}}, "[f(a=1)]")
        self.assertEqual((r["status"], r["details"]["error_type"]), ("wrong", "upstream_would_crash"))

    def test_unparsed_status(self):
        r = self.check("我無法完成")
        self.assertEqual((r["status"], r["score"]), ("unparsed", 0))
        self.assertTrue(r["verifier"].startswith("acebench-normal@"))


if __name__ == "__main__":
    unittest.main()
