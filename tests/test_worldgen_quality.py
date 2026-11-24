import json
import tempfile
import time
import unittest
import unittest.mock
from pathlib import Path

import store
import bridge
from bridge import _complete_sentence, _room_profile, _utterance
from pantheon import Pantheon
from worldgen import refresh


class FakeRecord:
    def __init__(self):
        self.agents=[
            {"id":1,"name":"Aster","tier":"worker","domain":"climate","status":"active",
             "tasks_verified":1,"tasks_attempted":2,"failures_streak":0,"curiosity":0.8},
            {"id":2,"name":"Kestrel","tier":"architect","domain":"orbital","status":"active",
             "tasks_verified":2,"tasks_attempted":4,"failures_streak":2,"curiosity":0.4},
        ]
        self.task={"id":5,"domain":"climate","difficulty":1,"question":"Analyze the monthly temperature series.",
                   "reward":20,"claimed_tick":3}
    def q(self,sql,params=()):
        if "FROM agents" in sql:return self.agents
        if "FROM instruments" in sql:
            return [{"tick":3,"name":"compute","args":"{}","result":"{\"value\":1.25}"}] if params[0]==1 else []
        if "FROM memory" in sql:
            return [{"id":8,"tick":3,"kind":"lesson","text":"Check units before comparing trends.","salience":0.9}]
        return []
    def one(self,sql,params=()):
        if "FROM tasks" in sql:return self.task if params[0]==1 else None
        if "FROM events" in sql:return {"id":4,"tick":3,"kind":"verified","text":"Aster completed a climate check."} if params[0]==1 else None
        return None
    def agent_by_name(self,name):
        return next((a for a in self.agents if a["name"].lower()==name.lower()),None)
    def recall(self,agent_id,query="",limit=1):
        return []


class SpeechQualityTests(unittest.TestCase):
    def test_complete_responses_are_preserved(self):
        self.assertEqual(_complete_sentence("I am working on task 5."),"I am working on task 5.")
    def test_clipped_final_clause_is_removed(self):
        self.assertEqual(_complete_sentence("The record shows a setback. That suggests"),"The record shows a setback.")
    def test_clipped_single_clause_is_withheld(self):
        self.assertEqual(_complete_sentence("I am working on climate task 5"),"")
    def test_numeric_decimals_do_not_look_like_sentence_boundaries(self):
        self.assertEqual(_complete_sentence("Expected 3.72965, got 3.3"),"")
    def test_clipped_speech_is_retried_and_replaced_with_complete_reply(self):
        class Relay:
            def __init__(self):
                self.calls=[]
                self.results=[
                    {"ok":True,"content":"I am on task 5. The series suggests","usage":{"prompt_tokens":20,"completion_tokens":8},"model":"beam-free","ms":10},
                    {"ok":True,"content":"Task 5 needs a trend check before I can claim a climate result.","usage":{"prompt_tokens":25,"completion_tokens":14},"model":"beam-free","ms":9},
                ]
            def chat(self,*args,**kwargs):
                self.calls.append((args,kwargs));return self.results.pop(0)
        relay=Relay();record=FakeRecord();agent=record.agents[0]
        with unittest.mock.patch.object(bridge.transport,"Relay",return_value=relay):
            line=_utterance(record,agent,{},"meeting","compare work",[],[_room_profile(record,a) for a in record.agents])
        self.assertEqual(line["text"],"Task 5 needs a trend check before I can claim a climate result.")
        self.assertTrue(line["ok"]);self.assertTrue(line["recovered"]);self.assertEqual(line["retries"],1)
        self.assertEqual(line["tokens"],67)
        self.assertEqual([c[1]["max_tokens"] for c in relay.calls],[1800,900])
    def test_two_incomplete_generations_do_not_publish_a_fragment(self):
        class Relay:
            def __init__(self):
                self.results=[{"ok":True,"content":"The colony record indicates","usage":{}},
                              {"ok":True,"content":"I might need to","usage":{}}]
            def chat(self,*args,**kwargs):return self.results.pop(0)
        record=FakeRecord();agent=record.agents[0]
        with unittest.mock.patch.object(bridge.transport,"Relay",return_value=Relay()):
            line=_utterance(record,agent,{},"meeting","compare work",[],[_room_profile(record,a) for a in record.agents])
        self.assertFalse(line["ok"]);self.assertEqual(line["text"],"");self.assertIn("incomplete",line["error"])


class WorldGenerationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.old_data,self.old_db=store.DATA,store.DB
        store.DATA=Path(self.temp.name)
        store.DB=Path(self.temp.name)/"console.db"
        self.addCleanup(self.cleanup_store)
    def cleanup_store(self):
        store.DATA,store.DB=self.old_data,self.old_db
        self.temp.cleanup()

    def test_needs_create_persistent_workboards_and_repeated_collaboration_place(self):
        record=FakeRecord()
        for i in range(2):
            store.save_assembly({"kind":"meeting","topic":"Compare recorded work","created":time.time()+i,
                                 "cis":["Aster","Kestrel"],"transcript":[]})
        first=refresh(record)
        self.assertEqual(len(first["artifacts"]),2)
        board=next(a for a in first["artifacts"] if a["owner"]=="Aster")
        self.assertEqual(board["kind"],"workboard")
        self.assertEqual(board["content"]["task"]["id"],5)
        self.assertEqual(board["content"]["tools"][0]["name"],"compute")
        self.assertIn("affect",board["content"])
        self.assertEqual(len(first["places"]),1)
        place=first["places"][0]
        self.assertLess((place["x"]**2+place["z"]**2)**0.5,30)
        self.assertEqual(place["interactions"],2)
        self.assertTrue(place["dynamic"])
        self.assertEqual(place["participants"],["Aster","Kestrel"])
        world=Pantheon(Path(self.temp.name)/"pantheon.json")
        world.dynamic_places=first["places"]
        world.artifacts=first["artifacts"]
        snapshot=world.snapshot(1234.0)
        self.assertIn(place["id"],[p["id"] for p in snapshot["places"]])
        self.assertEqual(len(snapshot["artifacts"]),2)
        second=refresh(record)
        self.assertEqual(second["places"][0]["x"],place["x"])
        self.assertEqual(second["places"][0]["z"],place["z"])
        board2=next(a for a in second["artifacts"] if a["owner"]=="Aster")
        self.assertEqual(board2["updated"],board["updated"])


if __name__=="__main__":
    unittest.main()
