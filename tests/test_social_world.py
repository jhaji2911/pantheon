import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))

from bridge import Record, _room_profile, _speech_messages, affect_for, settings_now
from pantheon import Pantheon


class AffectTests(unittest.TestCase):
    def test_labels_are_tied_to_record_cues(self):
        agent={"status":"active","failures_streak":2,"curiosity":0.9,"tasks_verified":0}
        task={"id":7,"domain":"climate"}
        got=affect_for(agent,task)
        self.assertEqual(got["label"],"strained")
        self.assertIn("failure streak 2",got["cues"])
        self.assertIn("holding task 7 (climate)",got["cues"])
        self.assertIn("not a claim",got["basis"])

    def test_peer_context_is_explicit_in_meeting_prompt(self):
        record=Record()
        speaker=record.agent_by_name("Aster")
        peer=record.agent_by_name("Kestrel")
        if not speaker or not peer:
            self.skipTest("seed colony CIs not present")
        context=[_room_profile(record,speaker),_room_profile(record,peer)]
        messages=_speech_messages(record,speaker,settings_now(),"talk about today's work",room_context=context)
        prompt=messages[0]["content"]
        self.assertIn("Other attendees",prompt)
        self.assertIn("Kestrel",prompt)
        self.assertIn("observed affect",prompt)
        self.assertIn("task",prompt)


class GatheringTests(unittest.TestCase):
    def test_attendees_walk_to_hall_and_release_back_to_routine(self):
        world=Pantheon(Path.home()/".hermes/cache/scratch/pantheon-test-no-write.json")
        world.register_agent("Aster","worker","quantum")
        world.register_agent("Kestrel","architect","orbital")
        names=world.begin_gathering(["Aster","Kestrel"],"meeting-test",100.0)
        self.assertEqual(names,["Aster","Kestrel"])
        self.assertNotEqual(world.agents["aster"]["gathering"]["z"],world.agents["kestrel"]["gathering"]["z"])
        arrival=max(b["arrive_at"] for b in world.agents.values())+0.1
        world.advance(arrival)
        snap=world.snapshot(arrival)
        gathered=[a for a in snap["agents"] if a["gathering"]]
        self.assertEqual(len(gathered),2)
        self.assertTrue(all(a["place"]=="hall" and "sitting" in a["activity"] for a in gathered))
        world.end_gathering("meeting-test",arrival+1)
        world.advance(arrival+1)
        self.assertFalse(any(b.get("gathering") for b in world.agents.values()))


if __name__=="__main__":
    unittest.main()
