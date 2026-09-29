"""字幕三方合并 API 的端到端测试（标准库 unittest + FastAPI TestClient）。"""

import unittest

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def cue(id, start, end, text="t", speaker=None):
    data = {"id": id, "start": start, "end": end, "text": text}
    if speaker is not None:
        data["speaker"] = speaker
    return data


def anchor(source, target):
    return {"source": source, "target": target}


class HealthTests(unittest.TestCase):
    def test_health(self):
        resp = client.get("/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "ok"})


class MergeTests(unittest.TestCase):
    def test_unchanged_three_versions_merge_clean(self):
        body = {
            "base": [cue("a", 0, 2, "hello")],
            "current": [cue("a", 0, 2, "hello")],
            "incoming": [cue("a", 0, 2, "hello")],
        }
        resp = client.post("/merge", json=body)
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        self.assertEqual(data["status"], "merged")
        self.assertEqual(data["count"], 1)

    def test_single_side_change_is_adopted(self):
        # current 单独修改文本；incoming 未动
        body = {
            "base": [cue("a", 0, 2, "hello")],
            "current": [cue("a", 0, 2, "hello!")],
            "incoming": [cue("a", 0, 2, "hello")],
        }
        resp = client.post("/merge", json=body)
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["cues"][0]["text"], "hello!")

    def test_both_sides_change_different_fields(self):
        # current 改时间，incoming 改文本：各自采纳
        body = {
            "base": [cue("a", 0, 2, "hello")],
            "current": [cue("a", 1, 3, "hello")],
            "incoming": [cue("a", 0, 2, "你好")],
        }
        resp = client.post("/merge", json=body)
        self.assertEqual(resp.status_code, 200, resp.text)
        merged = resp.json()["cues"][0]
        self.assertEqual((merged["start"], merged["end"]), (1, 3))
        self.assertEqual(merged["text"], "你好")

    def test_both_sides_change_to_same_value(self):
        body = {
            "base": [cue("a", 0, 2, "hello")],
            "current": [cue("a", 0, 2, "hi")],
            "incoming": [cue("a", 0, 2, "hi")],
        }
        resp = client.post("/merge", json=body)
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["cues"][0]["text"], "hi")

    def test_field_level_conflict_different_values(self):
        body = {
            "base": [cue("a", 0, 2, "hello")],
            "current": [cue("a", 0, 2, "hi")],
            "incoming": [cue("a", 0, 2, "yo")],
        }
        resp = client.post("/merge", json=body)
        self.assertEqual(resp.status_code, 409)
        data = resp.json()
        self.assertEqual(data["status"], "conflict")
        self.assertEqual(len(data["field_conflicts"]), 1)
        fc = data["field_conflicts"][0]
        self.assertEqual(fc["cue_id"], "a")
        self.assertEqual(fc["field"], "text")
        self.assertEqual(fc["base"], "hello")
        self.assertEqual(fc["current"], "hi")
        self.assertEqual(fc["incoming"], "yo")

    def test_both_delete_is_clean(self):
        body = {
            "base": [cue("a", 0, 2), cue("b", 3, 4)],
            "current": [cue("b", 3, 4)],
            "incoming": [cue("b", 3, 4)],
        }
        resp = client.post("/merge", json=body)
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual([c["id"] for c in resp.json()["cues"]], ["b"])

    def test_delete_vs_modify_is_conflict(self):
        # current 删除 a，incoming 修改 a
        body = {
            "base": [cue("a", 0, 2, "hello")],
            "current": [],
            "incoming": [cue("a", 0, 2, "hello!")],
        }
        resp = client.post("/merge", json=body)
        self.assertEqual(resp.status_code, 409)
        data = resp.json()
        self.assertEqual(data["status"], "conflict")
        self.assertEqual(len(data["cue_conflicts"]), 1)
        cc = data["cue_conflicts"][0]
        self.assertEqual(cc["cue_id"], "a")
        self.assertEqual(cc["type"], "delete_modify")
        self.assertEqual(cc["side"], "current")
        self.assertIn("text", cc["fields"])

    def test_delete_vs_unchanged_adopts_delete(self):
        # 一侧删除，另一侧原样保留：删除生效
        body = {
            "base": [cue("a", 0, 2, "hello")],
            "current": [],
            "incoming": [cue("a", 0, 2, "hello")],
        }
        resp = client.post("/merge", json=body)
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["count"], 0)

    def test_add_add_same_value_adopts(self):
        body = {
            "base": [],
            "current": [cue("n", 5, 7, "new")],
            "incoming": [cue("n", 5, 7, "new")],
        }
        resp = client.post("/merge", json=body)
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["cues"][0]["id"], "n")

    def test_add_add_different_value_is_conflict(self):
        body = {
            "base": [],
            "current": [cue("n", 5, 7, "new")],
            "incoming": [cue("n", 5, 7, "brand new")],
        }
        resp = client.post("/merge", json=body)
        self.assertEqual(resp.status_code, 409)
        cc = resp.json()["cue_conflicts"][0]
        self.assertEqual(cc["type"], "add_add")
        self.assertEqual(cc["fields"], ["text"])

    def test_result_sorted_by_start(self):
        body = {
            "base": [],
            "current": [cue("c", 10, 11, "late"), cue("a", 0, 1, "early")],
            "incoming": [cue("b", 5, 6, "mid")],
        }
        resp = client.post("/merge", json=body)
        self.assertEqual(resp.status_code, 200, resp.text)
        ids = [c["id"] for c in resp.json()["cues"]]
        self.assertEqual(ids, ["a", "b", "c"])

    def test_overlap_reported_without_merged_output(self):
        # 无冲突，但 current 新增的 cue 与 incoming 新增的 cue 时间重叠
        body = {
            "base": [],
            "current": [cue("a", 0, 5, "first")],
            "incoming": [cue("b", 3, 8, "second")],
        }
        resp = client.post("/merge", json=body)
        self.assertEqual(resp.status_code, 409)
        data = resp.json()
        self.assertEqual(data["status"], "overlap")
        self.assertNotIn("cues", data)
        self.assertEqual(len(data["overlaps"]), 1)
        ov = data["overlaps"][0]
        self.assertEqual(ov["cue_ids"], ["a", "b"])
        self.assertAlmostEqual(ov["start"], 3)
        self.assertAlmostEqual(ov["end"], 5)
        self.assertAlmostEqual(ov["overlap"], 2)

    def test_touching_intervals_are_not_overlap(self):
        # 首尾相接（end == start）不算重叠
        body = {
            "base": [],
            "current": [cue("a", 0, 5, "first")],
            "incoming": [cue("b", 5, 8, "second")],
        }
        resp = client.post("/merge", json=body)
        self.assertEqual(resp.status_code, 200, resp.text)

    def test_conflict_blocks_overlap_check(self):
        # 同时存在冲突和潜在重叠：报告冲突，不进入重叠检测
        body = {
            "base": [cue("a", 0, 2, "x")],
            "current": [cue("a", 0, 2, "one")],
            "incoming": [cue("a", 0, 2, "two")],
        }
        resp = client.post("/merge", json=body)
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()["status"], "conflict")

    def test_invalid_interval_rejected(self):
        body = {
            "base": [cue("a", 0, 2)],
            "current": [cue("a", 5, 2)],
            "incoming": [cue("a", 0, 2)],
        }
        resp = client.post("/merge", json=body)
        self.assertEqual(resp.status_code, 422)

    def test_duplicate_id_within_one_version_rejected(self):
        body = {
            "base": [cue("a", 0, 2), cue("a", 3, 4)],
            "current": [],
            "incoming": [],
        }
        resp = client.post("/merge", json=body)
        self.assertEqual(resp.status_code, 422)

    def test_speaker_none_equivalence(self):
        # base 未提供 speaker 与一侧显式给出 speaker: null 视为未修改
        body = {
            "base": [{"id": "a", "start": 0, "end": 2, "text": "x"}],
            "current": [
                {"id": "a", "start": 0, "end": 2, "text": "x", "speaker": None}
            ],
            "incoming": [
                {"id": "a", "start": 0, "end": 2, "text": "x", "speaker": "bob"}
            ],
        }
        resp = client.post("/merge", json=body)
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["cues"][0]["speaker"], "bob")


class ResolveTests(unittest.TestCase):
    # —— 无冲突：仅允许空决策 ——

    def test_no_conflict_empty_decisions_resolves(self):
        body = {
            "base": [cue("a", 0, 2, "hello")],
            "current": [cue("a", 0, 2, "hello!")],
            "incoming": [cue("a", 0, 2, "hello")],
        }
        resp = client.post("/resolve", json=body)
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        self.assertEqual(data["status"], "resolved")
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["cues"][0]["text"], "hello!")

    def test_no_conflict_empty_lists_resolves(self):
        resp = client.post(
            "/resolve",
            json={
                "base": [cue("a", 0, 2)],
                "current": [cue("a", 0, 2)],
                "incoming": [cue("a", 0, 2)],
                "field_choices": [],
                "cue_choices": [],
            },
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["status"], "resolved")

    def test_no_conflict_with_field_choice_is_unknown(self):
        body = {
            "base": [cue("a", 0, 2)],
            "current": [cue("a", 0, 2)],
            "incoming": [cue("a", 0, 2)],
            "field_choices": [
                {"cue_id": "a", "field": "text", "choice": "current"}
            ],
        }
        resp = client.post("/resolve", json=body)
        self.assertEqual(resp.status_code, 422)
        data = resp.json()
        self.assertEqual(data["status"], "decision_error")
        self.assertEqual(len(data["errors"]), 1)
        self.assertEqual(data["errors"][0]["type"], "unknown")

    def test_no_conflict_with_cue_choice_is_unknown(self):
        body = {
            "base": [cue("a", 0, 2)],
            "current": [cue("a", 0, 2)],
            "incoming": [cue("a", 0, 2)],
            "cue_choices": [{"cue_id": "a", "choice": "delete"}],
        }
        resp = client.post("/resolve", json=body)
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.json()["errors"][0]["type"], "unknown")

    # —— 字段级冲突 ——

    def test_field_conflict_resolve_pick_side(self):
        for choice, expected in [
            ("base", "hi"),
            ("current", "one"),
            ("incoming", "two"),
        ]:
            with self.subTest(choice=choice):
                body = {
                    "base": [cue("a", 0, 2, "hi")],
                    "current": [cue("a", 0, 2, "one")],
                    "incoming": [cue("a", 0, 2, "two")],
                    "field_choices": [
                        {"cue_id": "a", "field": "text", "choice": choice}
                    ],
                }
                resp = client.post("/resolve", json=body)
                self.assertEqual(resp.status_code, 200, resp.text)
                self.assertEqual(resp.json()["cues"][0]["text"], expected)

    def test_field_choice_merges_non_conflicting_fields(self):
        # current 改文本，incoming 改文本（冲突）与起点；起点单侧改动仍自动采纳
        body = {
            "base": [cue("a", 0, 2, "hi")],
            "current": [cue("a", 0, 2, "one")],
            "incoming": [cue("a", 1, 2, "two")],
            "field_choices": [
                {"cue_id": "a", "field": "text", "choice": "current"}
            ],
        }
        resp = client.post("/resolve", json=body)
        self.assertEqual(resp.status_code, 200, resp.text)
        resolved = resp.json()["cues"][0]
        self.assertEqual(resolved["text"], "one")
        self.assertEqual(resolved["start"], 1)

    def test_multiple_field_conflicts_on_same_cue(self):
        body = {
            "base": [cue("a", 0, 10, "keep")],
            "current": [cue("a", 8, 9, "cur")],
            "incoming": [cue("a", 1, 3, "inc")],
            "field_choices": [
                {"cue_id": "a", "field": "start", "choice": "incoming"},
                {"cue_id": "a", "field": "end", "choice": "current"},
                {"cue_id": "a", "field": "text", "choice": "base"},
            ],
        }
        resp = client.post("/resolve", json=body)
        self.assertEqual(resp.status_code, 200, resp.text)
        cue_out = resp.json()["cues"][0]
        self.assertEqual((cue_out["start"], cue_out["end"], cue_out["text"]), (1, 9, "keep"))

    def test_missing_field_choice_is_422(self):
        body = {
            "base": [cue("a", 0, 2, "hi")],
            "current": [cue("a", 0, 2, "one")],
            "incoming": [cue("a", 0, 2, "two")],
        }
        resp = client.post("/resolve", json=body)
        self.assertEqual(resp.status_code, 422)
        errors = resp.json()["errors"]
        self.assertTrue(any(e["type"] == "missing" for e in errors))

    def test_missing_multiple_field_choices_all_reported(self):
        body = {
            "base": [cue("a", 0, 10, "keep")],
            "current": [cue("a", 8, 9, "cur")],
            "incoming": [cue("a", 1, 3, "inc")],
        }
        resp = client.post("/resolve", json=body)
        self.assertEqual(resp.status_code, 422)
        missing = {e["field"] for e in resp.json()["errors"] if e["type"] == "missing"}
        self.assertEqual(missing, {"start", "end", "text"})

    def test_unknown_field_choice_is_422(self):
        body = {
            "base": [cue("a", 0, 2, "hi")],
            "current": [cue("a", 0, 2, "one")],
            "incoming": [cue("a", 0, 2, "two")],
            "field_choices": [
                {"cue_id": "a", "field": "text", "choice": "current"},
                {"cue_id": "a", "field": "start", "choice": "current"},
            ],
        }
        resp = client.post("/resolve", json=body)
        self.assertEqual(resp.status_code, 422)
        errors = resp.json()["errors"]
        unknown = [e for e in errors if e["type"] == "unknown"]
        self.assertEqual(len(unknown), 1)
        self.assertEqual(unknown[0]["field"], "start")

    def test_unknown_cue_id_in_field_choice_is_422(self):
        body = {
            "base": [cue("a", 0, 2)],
            "current": [cue("a", 0, 2)],
            "incoming": [cue("a", 0, 2)],
            "field_choices": [
                {"cue_id": "ghost", "field": "text", "choice": "base"}
            ],
        }
        resp = client.post("/resolve", json=body)
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.json()["errors"][0]["type"], "unknown")

    def test_duplicate_field_choice_is_422(self):
        body = {
            "base": [cue("a", 0, 2, "hi")],
            "current": [cue("a", 0, 2, "one")],
            "incoming": [cue("a", 0, 2, "two")],
            "field_choices": [
                {"cue_id": "a", "field": "text", "choice": "current"},
                {"cue_id": "a", "field": "text", "choice": "incoming"},
            ],
        }
        resp = client.post("/resolve", json=body)
        self.assertEqual(resp.status_code, 422)
        types = [e["type"] for e in resp.json()["errors"]]
        self.assertEqual(types, ["duplicate"])

    def test_field_choice_on_cue_conflict_is_type_mismatch(self):
        body = {
            "base": [cue("a", 0, 2, "hi")],
            "current": [],
            "incoming": [cue("a", 0, 2, "two")],
            "field_choices": [
                {"cue_id": "a", "field": "text", "choice": "incoming"}
            ],
        }
        resp = client.post("/resolve", json=body)
        self.assertEqual(resp.status_code, 422)
        errors = resp.json()["errors"]
        self.assertTrue(any(e["type"] == "type_mismatch" for e in errors))
        self.assertTrue(any(e["type"] == "missing" and e["field"] is None for e in errors))

    # —— cue 级冲突 ——

    def test_delete_modify_pick_incoming(self):
        body = {
            "base": [cue("a", 0, 2, "hi")],
            "current": [],
            "incoming": [cue("a", 0, 2, "two")],
            "cue_choices": [{"cue_id": "a", "choice": "incoming"}],
        }
        resp = client.post("/resolve", json=body)
        self.assertEqual(resp.status_code, 200, resp.text)
        cues = resp.json()["cues"]
        self.assertEqual(len(cues), 1)
        self.assertEqual(cues[0]["text"], "two")

    def test_delete_modify_pick_deleted_side_deletes(self):
        # current 已删除，选择 current 等同删除
        body = {
            "base": [cue("a", 0, 2, "hi")],
            "current": [],
            "incoming": [cue("a", 0, 2, "two")],
            "cue_choices": [{"cue_id": "a", "choice": "current"}],
        }
        resp = client.post("/resolve", json=body)
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["count"], 0)

    def test_delete_modify_choice_delete(self):
        body = {
            "base": [cue("a", 0, 2, "hi")],
            "current": [],
            "incoming": [cue("a", 0, 2, "two")],
            "cue_choices": [{"cue_id": "a", "choice": "delete"}],
        }
        resp = client.post("/resolve", json=body)
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["count"], 0)

    def test_add_add_pick_each_side(self):
        for choice, expected in [("current", "new"), ("incoming", "brand")]:
            with self.subTest(choice=choice):
                body = {
                    "base": [],
                    "current": [cue("n", 5, 7, "new")],
                    "incoming": [cue("n", 5, 7, "brand")],
                    "cue_choices": [{"cue_id": "n", "choice": choice}],
                }
                resp = client.post("/resolve", json=body)
                self.assertEqual(resp.status_code, 200, resp.text)
                self.assertEqual(resp.json()["cues"][0]["text"], expected)

    def test_invalid_interval_cue_conflict_pick_side(self):
        # current 只改起点、incoming 只改终点，自动合并为 [8,3] 非法
        body = {
            "base": [cue("a", 0, 10)],
            "current": [cue("a", 8, 10)],
            "incoming": [cue("a", 0, 3)],
        }
        conflict = client.post("/merge", json=body).json()
        self.assertEqual(conflict["cue_conflicts"][0]["type"], "invalid_interval")

        resolved_body = dict(body)
        resolved_body["cue_choices"] = [{"cue_id": "a", "choice": "current"}]
        resp = client.post("/resolve", json=resolved_body)
        self.assertEqual(resp.status_code, 200, resp.text)
        out = resp.json()["cues"][0]
        self.assertEqual((out["start"], out["end"]), (8, 10))

    def test_missing_cue_choice_is_422(self):
        body = {
            "base": [cue("a", 0, 2, "hi")],
            "current": [],
            "incoming": [cue("a", 0, 2, "two")],
        }
        resp = client.post("/resolve", json=body)
        self.assertEqual(resp.status_code, 422)
        errors = resp.json()["errors"]
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["type"], "missing")
        self.assertEqual(errors[0]["cue_id"], "a")

    def test_unknown_cue_choice_is_422(self):
        body = {
            "base": [cue("a", 0, 2)],
            "current": [cue("a", 0, 2)],
            "incoming": [cue("a", 0, 2)],
            "cue_choices": [{"cue_id": "ghost", "choice": "incoming"}],
        }
        resp = client.post("/resolve", json=body)
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.json()["errors"][0]["type"], "unknown")

    def test_duplicate_cue_choice_is_422(self):
        body = {
            "base": [cue("a", 0, 2, "hi")],
            "current": [],
            "incoming": [cue("a", 0, 2, "two")],
            "cue_choices": [
                {"cue_id": "a", "choice": "delete"},
                {"cue_id": "a", "choice": "incoming"},
            ],
        }
        resp = client.post("/resolve", json=body)
        self.assertEqual(resp.status_code, 422)
        self.assertEqual([e["type"] for e in resp.json()["errors"]], ["duplicate"])

    def test_cue_choice_on_field_conflict_is_type_mismatch(self):
        body = {
            "base": [cue("a", 0, 2, "hi")],
            "current": [cue("a", 0, 2, "one")],
            "incoming": [cue("a", 0, 2, "two")],
            "cue_choices": [{"cue_id": "a", "choice": "delete"}],
        }
        resp = client.post("/resolve", json=body)
        self.assertEqual(resp.status_code, 422)
        errors = resp.json()["errors"]
        self.assertTrue(any(e["type"] == "type_mismatch" and e["field"] is None for e in errors))

    def test_invalid_choice_value_is_422(self):
        body = {
            "base": [cue("a", 0, 2, "hi")],
            "current": [],
            "incoming": [cue("a", 0, 2, "two")],
            "cue_choices": [{"cue_id": "a", "choice": "base"}],
        }
        resp = client.post("/resolve", json=body)
        self.assertEqual(resp.status_code, 422)

    # —— 应用决策后的统一校验（409，不输出部分结果）——

    def test_field_decisions_producing_invalid_interval_409(self):
        body = {
            "base": [cue("a", 0, 10, "keep")],
            "current": [cue("a", 8, 9, "cur")],
            "incoming": [cue("a", 1, 3, "inc")],
            "field_choices": [
                {"cue_id": "a", "field": "start", "choice": "current"},
                {"cue_id": "a", "field": "end", "choice": "incoming"},
                {"cue_id": "a", "field": "text", "choice": "base"},
            ],
        }
        resp = client.post("/resolve", json=body)
        self.assertEqual(resp.status_code, 409)
        data = resp.json()
        self.assertEqual(data["status"], "timeline_error")
        self.assertEqual(data["invalid_intervals"], ["a"])
        self.assertEqual(data["overlaps"], [])
        self.assertNotIn("cues", data)

    def test_field_decisions_producing_overlap_409(self):
        # a、b 各自字段冲突；选 incoming 侧时间后 a=[1,4]、b=[3,12] 重叠
        body = {
            "base": [cue("a", 0, 10, "x"), cue("b", 10, 12, "y")],
            "current": [cue("a", 8, 9, "cx"), cue("b", 9, 12, "cy")],
            "incoming": [cue("a", 1, 4, "ix"), cue("b", 3, 12, "iy")],
            "field_choices": [
                {"cue_id": "a", "field": "start", "choice": "incoming"},
                {"cue_id": "a", "field": "end", "choice": "incoming"},
                {"cue_id": "a", "field": "text", "choice": "incoming"},
                {"cue_id": "b", "field": "start", "choice": "incoming"},
                {"cue_id": "b", "field": "text", "choice": "incoming"},
            ],
        }
        resp = client.post("/resolve", json=body)
        self.assertEqual(resp.status_code, 409)
        data = resp.json()
        self.assertEqual(data["status"], "timeline_error")
        self.assertEqual(data["invalid_intervals"], [])
        self.assertEqual(len(data["overlaps"]), 1)
        self.assertEqual(data["overlaps"][0]["cue_ids"], ["a", "b"])

    def test_touching_intervals_after_decisions_resolve(self):
        # 同样的冲突，选 current 侧：a=[8,9]、b=[9,12]，首尾相接合法
        body = {
            "base": [cue("a", 0, 10, "x"), cue("b", 10, 12, "y")],
            "current": [cue("a", 8, 9, "cx"), cue("b", 9, 12, "cy")],
            "incoming": [cue("a", 1, 4, "ix"), cue("b", 3, 12, "iy")],
            "field_choices": [
                {"cue_id": "a", "field": "start", "choice": "current"},
                {"cue_id": "a", "field": "end", "choice": "current"},
                {"cue_id": "a", "field": "text", "choice": "current"},
                {"cue_id": "b", "field": "start", "choice": "current"},
                {"cue_id": "b", "field": "text", "choice": "current"},
            ],
        }
        resp = client.post("/resolve", json=body)
        self.assertEqual(resp.status_code, 200, resp.text)
        ids = [c["id"] for c in resp.json()["cues"]]
        self.assertEqual(ids, ["a", "b"])

    def test_no_conflict_but_overlap_still_409(self):
        body = {
            "base": [],
            "current": [cue("a", 0, 5, "first")],
            "incoming": [cue("b", 3, 8, "second")],
        }
        resp = client.post("/resolve", json=body)
        self.assertEqual(resp.status_code, 409)
        data = resp.json()
        self.assertEqual(data["status"], "timeline_error")
        self.assertEqual(len(data["overlaps"]), 1)

    def test_resolved_timeline_is_sorted_by_time(self):
        # cue 级冲突与干净合并同时存在，结果统一按时间排序
        body = {
            "base": [
                cue("a", 0, 2, "hi"),
                cue("d", 20, 21, "keep"),
            ],
            "current": [cue("d", 20, 21, "keep")],
            "incoming": [
                cue("a", 0, 2, "two"),
                cue("d", 20, 21, "keep"),
                cue("c", 10, 11, "late"),
            ],
            "cue_choices": [{"cue_id": "a", "choice": "incoming"}],
        }
        # 再让 current 单独新增一条更早的 cue
        body["current"].append(cue("b", 5, 6, "mid"))
        resp = client.post("/resolve", json=body)
        self.assertEqual(resp.status_code, 200, resp.text)
        ids = [c["id"] for c in resp.json()["cues"]]
        self.assertEqual(ids, ["a", "b", "c", "d"])


class RetimeTests(unittest.TestCase):
    def test_linear_scale_within_single_segment(self):
        # anchors (0,0)-(10,20)：整体 2 倍速
        body = {
            "cues": [cue("a", 1, 3, "hello", speaker="bob")],
            "anchors": [anchor(0, 0), anchor(10, 20)],
        }
        resp = client.post("/retime", json=body)
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        self.assertEqual(data["status"], "retimed")
        self.assertEqual(data["count"], 1)
        out = data["cues"][0]
        self.assertAlmostEqual(out["start"], 2.0)
        self.assertAlmostEqual(out["end"], 6.0)
        # id / text / speaker 保持不变
        self.assertEqual((out["id"], out["text"], out["speaker"]), ("a", "hello", "bob"))

    def test_piecewise_interpolation_across_segments(self):
        # 0->0, 10->20, 20->25：区间内分段插值
        body = {
            "cues": [
                cue("a", 5, 15),   # 10（首段）, 22.5（次段）
                cue("b", 12, 18),  # 21, 24
            ],
            "anchors": [anchor(0, 0), anchor(10, 20), anchor(20, 25)],
        }
        resp = client.post("/retime", json=body)
        self.assertEqual(resp.status_code, 200, resp.text)
        cues = resp.json()["cues"]
        self.assertAlmostEqual(cues[0]["start"], 10.0)
        self.assertAlmostEqual(cues[0]["end"], 22.5)
        self.assertAlmostEqual(cues[1]["start"], 21.0)
        self.assertAlmostEqual(cues[1]["end"], 24.0)

    def test_exact_anchor_positions_map_to_target(self):
        body = {
            "cues": [cue("a", 0, 10), cue("b", 10, 20)],
            "anchors": [anchor(0, 0), anchor(10, 20), anchor(20, 25)],
        }
        resp = client.post("/retime", json=body)
        self.assertEqual(resp.status_code, 200, resp.text)
        cues = resp.json()["cues"]
        self.assertAlmostEqual(cues[0]["start"], 0.0)
        self.assertAlmostEqual(cues[0]["end"], 20.0)
        self.assertAlmostEqual(cues[1]["start"], 20.0)
        self.assertAlmostEqual(cues[1]["end"], 25.0)

    def test_extrapolation_beyond_outer_anchors(self):
        # 10->5, 20->15（斜率 1）：t=0 外推为 -5，t=30 外推为 25
        body = {
            "cues": [cue("far", 30, 31)],
            "anchors": [anchor(10, 5), anchor(20, 15)],
        }
        resp = client.post("/retime", json=body)
        self.assertEqual(resp.status_code, 200, resp.text)
        out = resp.json()["cues"][0]
        self.assertAlmostEqual(out["start"], 25.0)
        self.assertAlmostEqual(out["end"], 26.0)

    def test_cue_spanning_anchor_uses_independent_endpoint_mapping(self):
        # 一条 cue 跨越锚点：start 在首段、end 在次段，分别独立计算
        body = {
            "cues": [cue("span", 5, 15, "cross")],
            "anchors": [anchor(0, 0), anchor(10, 20), anchor(20, 25)],
        }
        resp = client.post("/retime", json=body)
        self.assertEqual(resp.status_code, 200, resp.text)
        out = resp.json()["cues"][0]
        self.assertAlmostEqual(out["start"], 10.0)
        self.assertAlmostEqual(out["end"], 22.5)

    def test_output_preserves_input_order(self):
        body = {
            "cues": [
                cue("late", 80, 81),
                cue("early", 1, 2),
                cue("mid", 40, 41),
            ],
            "anchors": [anchor(0, 0), anchor(100, 100)],
        }
        resp = client.post("/retime", json=body)
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(
            [c["id"] for c in resp.json()["cues"]], ["late", "early", "mid"]
        )

    def test_identity_anchors_leave_times_unchanged(self):
        body = {
            "cues": [cue("a", 0, 0.5), cue("b", 100, 100.25)],
            "anchors": [anchor(0, 0), anchor(100, 100)],
        }
        resp = client.post("/retime", json=body)
        self.assertEqual(resp.status_code, 200, resp.text)
        cues = resp.json()["cues"]
        self.assertAlmostEqual(cues[0]["start"], 0.0)
        self.assertAlmostEqual(cues[0]["end"], 0.5)
        self.assertAlmostEqual(cues[1]["start"], 100.0)
        self.assertAlmostEqual(cues[1]["end"], 100.25)

    def test_negative_mapped_time_returns_409_with_all_cue_ids(self):
        # 10->5, 20->15（斜率 1）：start=0/0.5 外推为 -5/-4.5；中间 cue 合法
        body = {
            "cues": [
                cue("bad-start", 0, 11),    # -5, 6（负）
                cue("ok", 12, 13),          #  7, 8（合法，但不输出部分结果）
                cue("bad-end", 0.5, 11),    # -4.5, 6（负）
            ],
            "anchors": [anchor(10, 5), anchor(20, 15)],
        }
        resp = client.post("/retime", json=body)
        self.assertEqual(resp.status_code, 409)
        data = resp.json()
        self.assertEqual(data["status"], "retime_error")
        self.assertNotIn("cues", data)
        # 列出全部相关 cue id，按输入顺序去重
        self.assertEqual(data["cue_ids"], ["bad-start", "bad-end"])

    def test_negative_extrapolation_at_first_anchor(self):
        # 首个锚点 source>0、target 较小：首段外推使早于锚点的时间变负
        body = {
            "cues": [cue("a", 4, 8)],  # -1, 3
            "anchors": [anchor(10, 5), anchor(20, 15)],
        }
        resp = client.post("/retime", json=body)
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()["cue_ids"], ["a"])

    def test_float_collapsed_interval_is_409(self):
        # 锚点合法（target 严格递增 1 ULP），但极窄区间映射后两端四舍五入为
        # 同一浮点数 → end <= start，判为非法区间
        body = {
            "cues": [
                {"id": "tiny", "start": 5.000000000000001, "end": 5.000000000000002, "text": "x"}
            ],
            "anchors": [
                anchor(0, 1.0),
                anchor(10, 1.0000000000000002),
            ],
        }
        resp = client.post("/retime", json=body)
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()["cue_ids"], ["tiny"])

    def test_duplicate_ids_allowed_and_both_reported_once(self):
        # /retime 不做 id 去重；同一坏 id 只列一次
        body = {
            "cues": [
                cue("dup", 0, 11),
                cue("dup", 0, 11),
                cue("ok", 15, 16),
            ],
            "anchors": [anchor(10, 5), anchor(20, 15)],
        }
        resp = client.post("/retime", json=body)
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()["cue_ids"], ["dup"])

    def test_fewer_than_two_anchors_is_422(self):
        for anchors in ([], [anchor(0, 0)]):
            with self.subTest(n=len(anchors)):
                resp = client.post(
                    "/retime", json={"cues": [cue("a", 0, 1)], "anchors": anchors}
                )
                self.assertEqual(resp.status_code, 422)

    def test_non_increasing_source_anchors_is_422(self):
        # source 相等（非严格递增）
        body = {
            "cues": [cue("a", 0, 1)],
            "anchors": [anchor(0, 0), anchor(0, 10), anchor(10, 20)],
        }
        self.assertEqual(client.post("/retime", json=body).status_code, 422)
        # source 降序
        body["anchors"] = [anchor(10, 0), anchor(0, 10)]
        self.assertEqual(client.post("/retime", json=body).status_code, 422)

    def test_non_increasing_target_anchors_is_422(self):
        body = {
            "cues": [cue("a", 0, 1)],
            "anchors": [anchor(0, 10), anchor(10, 10), anchor(20, 20)],
        }
        self.assertEqual(client.post("/retime", json=body).status_code, 422)
        body["anchors"] = [anchor(0, 20), anchor(10, 10)]
        self.assertEqual(client.post("/retime", json=body).status_code, 422)

    def test_negative_anchor_values_is_422(self):
        body = {
            "cues": [cue("a", 0, 1)],
            "anchors": [anchor(-1, 0), anchor(10, 10)],
        }
        self.assertEqual(client.post("/retime", json=body).status_code, 422)
        body["anchors"] = [anchor(0, -1), anchor(10, 10)]
        self.assertEqual(client.post("/retime", json=body).status_code, 422)

    def test_empty_cues_retimes_to_empty_list(self):
        body = {"cues": [], "anchors": [anchor(0, 0), anchor(10, 10)]}
        resp = client.post("/retime", json=body)
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        self.assertEqual(data["status"], "retimed")
        self.assertEqual(data["cues"], [])
        self.assertEqual(data["count"], 0)


def sel(start, end):
    return {"start": start, "end": end}


class SpliceTests(unittest.TestCase):
    def test_empty_selections_returns_empty_list_and_zero(self):
        body = {"cues": [cue("a", 0, 2)], "selections": []}
        resp = client.post("/splice", json=body)
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        self.assertEqual(data["status"], "spliced")
        self.assertEqual(data["cues"], [])
        self.assertEqual(data["count"], 0)
        self.assertEqual(data["total_duration"], 0)

    def test_empty_body_defaults_to_empty(self):
        resp = client.post("/splice", json={})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(
            resp.json(),
            {"status": "spliced", "cues": [], "count": 0, "total_duration": 0.0},
        )

    def test_single_selection_within_one_cue(self):
        body = {
            "cues": [cue("a", 0, 10, "hello", speaker="bob")],
            "selections": [sel(2, 5)],
        }
        resp = client.post("/splice", json=body)
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        self.assertAlmostEqual(data["total_duration"], 3.0)
        self.assertEqual(data["count"], 1)
        out = data["cues"][0]
        self.assertEqual(out["id"], "a#0")
        self.assertEqual(out["source_id"], "a")
        self.assertEqual(out["selection"], 0)
        self.assertAlmostEqual(out["start"], 0.0)
        self.assertAlmostEqual(out["end"], 3.0)
        self.assertEqual((out["text"], out["speaker"]), ("hello", "bob"))

    def test_selection_containing_multiple_cues(self):
        body = {
            "cues": [cue("a", 0, 2, "one"), cue("b", 3, 5, "two")],
            "selections": [sel(0, 10)],
        }
        resp = client.post("/splice", json=body)
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        self.assertEqual(data["count"], 2)
        self.assertAlmostEqual(data["total_duration"], 10.0)
        self.assertEqual(
            [(c["id"], c["start"], c["end"]) for c in data["cues"]],
            [("a#0", 0.0, 2.0), ("b#0", 3.0, 5.0)],
        )
        # 片段之间的空白（2-3、5-10）计入总时长但不产生 cue
        self.assertEqual([c["source_id"] for c in data["cues"]], ["a", "b"])

    def test_crossing_boundary_cues_are_cut(self):
        # cue 横跨选区左右边界，两头裁断
        body = {
            "cues": [cue("a", 0, 10)],
            "selections": [sel(3, 7)],
        }
        resp = client.post("/splice", json=body)
        self.assertEqual(resp.status_code, 200, resp.text)
        out = resp.json()["cues"][0]
        self.assertAlmostEqual(out["start"], 0.0)
        self.assertAlmostEqual(out["end"], 4.0)
        self.assertEqual(out["source_id"], "a")

    def test_cue_starting_before_selection_keeps_relative_offset(self):
        body = {
            "cues": [cue("a", 2, 8)],
            "selections": [sel(5, 10)],
        }
        resp = client.post("/splice", json=body)
        self.assertEqual(resp.status_code, 200, resp.text)
        out = resp.json()["cues"][0]
        # 交集 [5,8)，相对选区起点 0..3
        self.assertAlmostEqual(out["start"], 0.0)
        self.assertAlmostEqual(out["end"], 3.0)

    def test_cue_starting_inside_selection(self):
        body = {
            "cues": [cue("a", 6, 8)],
            "selections": [sel(0, 10)],
        }
        resp = client.post("/splice", json=body)
        self.assertEqual(resp.status_code, 200, resp.text)
        out = resp.json()["cues"][0]
        self.assertAlmostEqual(out["start"], 6.0)
        self.assertAlmostEqual(out["end"], 8.0)

    def test_output_time_equals_prior_durations_plus_relative_time(self):
        # 选区乱序；前两个选区总时长 4+2=6 为第三个选区的偏移
        body = {
            "cues": [cue("a", 0, 100, "hi")],
            "selections": [sel(10, 14), sel(0, 2), sel(20, 30)],
        }
        resp = client.post("/splice", json=body)
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        self.assertAlmostEqual(data["total_duration"], 16.0)
        cues = data["cues"]
        self.assertEqual([c["selection"] for c in cues], [0, 1, 2])
        self.assertAlmostEqual(cues[0]["start"], 0.0)
        self.assertAlmostEqual(cues[0]["end"], 4.0)
        self.assertAlmostEqual(cues[1]["start"], 4.0)
        self.assertAlmostEqual(cues[1]["end"], 6.0)
        self.assertAlmostEqual(cues[2]["start"], 6.0)
        self.assertAlmostEqual(cues[2]["end"], 16.0)

    def test_overlapping_and_duplicate_selections_each_emit_piece(self):
        # 两个选区相互重叠且重复同一区间；同一原 cue 生成多个不同 id
        body = {
            "cues": [cue("a", 0, 10)],
            "selections": [sel(0, 5), sel(3, 8), sel(3, 8)],
        }
        resp = client.post("/splice", json=body)
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        self.assertAlmostEqual(data["total_duration"], 15.0)
        self.assertEqual(data["count"], 3)
        ids = [c["id"] for c in data["cues"]]
        self.assertEqual(ids, ["a#0", "a#1", "a#2"])
        self.assertEqual(len(set(ids)), 3)
        self.assertEqual([c["source_id"] for c in data["cues"]], ["a"] * 3)
        self.assertAlmostEqual(data["cues"][1]["start"], 5.0)
        self.assertAlmostEqual(data["cues"][1]["end"], 10.0)
        self.assertAlmostEqual(data["cues"][2]["start"], 10.0)
        self.assertAlmostEqual(data["cues"][2]["end"], 15.0)

    def test_gap_and_selection_beyond_source_count_into_duration(self):
        body = {
            "cues": [cue("a", 0, 1)],
            "selections": [sel(5, 6), sel(100, 110)],
        }
        resp = client.post("/splice", json=body)
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        # 两个选区都不与任何 cue 相交：无片段，但总时长 1+10=11
        self.assertEqual(data["cues"], [])
        self.assertAlmostEqual(data["total_duration"], 11.0)

    def test_touching_intersection_is_not_included(self):
        # cue.end == sel.start：仅端点相接，不严格相交
        body = {
            "cues": [cue("a", 0, 5)],
            "selections": [sel(5, 10)],
        }
        resp = client.post("/splice", json=body)
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        self.assertEqual(data["cues"], [])
        self.assertAlmostEqual(data["total_duration"], 5.0)

    def test_within_selection_cues_ordered_by_source_time(self):
        # cues 在请求中乱序；选区内仍按源时间顺序输出
        body = {
            "cues": [
                cue("late", 8, 9),
                cue("early", 1, 2),
                cue("mid", 4, 5),
            ],
            "selections": [sel(0, 10)],
        }
        resp = client.post("/splice", json=body)
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(
            [c["source_id"] for c in resp.json()["cues"]],
            ["early", "mid", "late"],
        )

    def test_text_and_speaker_preserved(self):
        body = {
            "cues": [
                {"id": "a", "start": 0, "end": 10, "text": "你好，世界", "speaker": "alice"}
            ],
            "selections": [sel(2, 4)],
        }
        resp = client.post("/splice", json=body)
        self.assertEqual(resp.status_code, 200, resp.text)
        out = resp.json()["cues"][0]
        self.assertEqual(out["text"], "你好，世界")
        self.assertEqual(out["speaker"], "alice")

    def test_duplicate_source_id_is_422(self):
        body = {
            "cues": [cue("a", 0, 2), cue("a", 3, 4)],
            "selections": [sel(0, 10)],
        }
        resp = client.post("/splice", json=body)
        self.assertEqual(resp.status_code, 422)

    def test_overlapping_source_timeline_is_422(self):
        body = {
            "cues": [cue("a", 0, 5), cue("b", 4, 8)],
            "selections": [sel(0, 10)],
        }
        resp = client.post("/splice", json=body)
        self.assertEqual(resp.status_code, 422)

    def test_touching_source_intervals_are_allowed(self):
        # 首尾相接（end == start）不算源时间轴重叠
        body = {
            "cues": [cue("a", 0, 5), cue("b", 5, 8)],
            "selections": [sel(0, 10)],
        }
        resp = client.post("/splice", json=body)
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(
            [c["source_id"] for c in resp.json()["cues"]], ["a", "b"]
        )

    def test_selection_end_must_be_greater_than_start(self):
        for body in (
            {"cues": [], "selections": [sel(5, 5)]},
            {"cues": [], "selections": [sel(6, 2)]},
        ):
            with self.subTest(sel=body["selections"]):
                self.assertEqual(client.post("/splice", json=body).status_code, 422)

    def test_negative_selection_endpoint_is_422(self):
        body = {"cues": [], "selections": [{"start": -1, "end": 2}]}
        self.assertEqual(client.post("/splice", json=body).status_code, 422)
        body = {"cues": [], "selections": [{"start": 0, "end": -1}]}
        self.assertEqual(client.post("/splice", json=body).status_code, 422)

    def test_float_seconds_supported(self):
        body = {
            "cues": [cue("a", 0.125, 0.625)],
            "selections": [sel(0.0, 0.5)],
        }
        resp = client.post("/splice", json=body)
        self.assertEqual(resp.status_code, 200, resp.text)
        out = resp.json()["cues"][0]
        self.assertAlmostEqual(out["start"], 0.125)
        self.assertAlmostEqual(out["end"], 0.5)
        self.assertAlmostEqual(resp.json()["total_duration"], 0.5)


if __name__ == "__main__":
    unittest.main()
