import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import store
from modules import world_builder
import llm


class FakeRecord:
    def q(self, sql, params=()):
        if "FROM events" in sql:
            return [{"tick": 12, "kind": "promoted", "text": "Tessellate became a specialist."}]
        if "FROM agents" in sql:
            return [{"name": "Tessellate", "tier": "specialist", "domain": "world", "status": "active"}]
        return []

    def tick(self):
        return 12


class FakeRelay:
    def __init__(self, cost=0, billing="go"):
        self.cost = cost
        self.billing = billing
        self.calls = []

    def chat(self, model, messages, **kwargs):
        self.calls.append((model, messages, kwargs))
        return {"ok": True, "model": model, "content":
                '{"kind":"car","name":"Agora electric","description":"A compact shared town car.",'
                '"color":"#8ba4a8","width":4.2,"depth":2.0,"height":1.6}',
                "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150,
                          "cost": self.cost, "opencode": {"billing_source": self.billing}}}


class WorldBuilderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        # The billing guards are colony-mode behaviour; test them even in a standalone checkout.
        standalone = patch.object(llm, "STANDALONE", False)
        standalone.start()
        self.addCleanup(standalone.stop)
        self.old_data, self.old_db = store.DATA, store.DB
        store.DATA = Path(self.temp.name)
        store.DB = Path(self.temp.name) / "console.db"
        self.addCleanup(self.cleanup)

    def cleanup(self):
        store.DATA, store.DB = self.old_data, self.old_db
        self.temp.cleanup()

    def test_validates_schema_and_bounds(self):
        design = world_builder.validate_design({"kind":"car","name":"A","description":"Town car",
            "color":"#abcdef","width":4,"depth":2,"height":1.4})
        self.assertEqual(design["kind"], "car")
        bare_hex = world_builder.validate_design({"kind":"car","name":"A","description":"Town car",
            "color":"abcdef","width":4,"depth":2,"height":1.4})
        self.assertEqual(bare_hex["color"], "#abcdef")
        named = world_builder.validate_design({"kind":"car","name":"A","description":"Town car",
            "color":"silver blue","width":4,"depth":2,"height":1.4})
        self.assertRegex(named["color"], r"^#[0-9a-f]{6}$")
        clamped = world_builder.validate_design({"kind":"car","name":"A","description":"Town car",
            "color":"#abcdef","width":400,"depth":2,"height":1.4})
        self.assertEqual(clamped["width"], 5.5)
        with self.assertRaises(ValueError):
            world_builder.validate_design({"kind":"car","name":"A","description":"Town car",
                "color":"!!!","width":4,"depth":2,"height":1.4})

    def test_extracts_json_without_accepting_truncated_output(self):
        self.assertEqual(world_builder._extract_json('prefix {"kind":"park"} suffix'), {"kind":"park"})
        with self.assertRaises(ValueError):
            world_builder._extract_json('{"kind":"park"')

    def test_live_build_result_persists_as_vinod_owned_with_model_provenance(self):
        relay = FakeRelay()
        result = world_builder.create_asset("Add a useful town car", FakeRecord(), relay)
        self.assertEqual(result["status"], 201)
        asset = result["asset"]
        self.assertEqual(asset["owner"], "Vinod Chanda")
        self.assertEqual(asset["owner_profile"], "cc-operator")
        self.assertEqual(asset["model"], world_builder.MODEL)
        self.assertEqual(asset["billing_source"], "go")
        self.assertEqual(asset["cost"], 0)
        self.assertEqual(store.world_assets()[0]["id"], asset["id"])
        self.assertTrue(-70 < asset["x"] < 70 and -70 < asset["z"] < 70)

    def test_refuses_nonzero_billing_without_saving(self):
        result = world_builder.create_asset("Add a car", FakeRecord(), FakeRelay(cost=0.01))
        self.assertEqual(result["status"], 502)
        self.assertFalse(store.world_assets())

    def test_refuses_non_go_billing_without_saving(self):
        result = world_builder.create_asset("Add a car", FakeRecord(), FakeRelay(billing="api"))
        self.assertEqual(result["status"], 502)
        self.assertFalse(store.world_assets())


if __name__ == "__main__":
    unittest.main()
