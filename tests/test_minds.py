import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))

import frontier
import life
import minds
import research
import store
from pantheon import PLACES, Pantheon


class ScriptedRelay:
    """Same surface as colony.transport.Relay; reports zero-cost Go billing unless told not to."""
    def __init__(self,decisions,billing="go",allowance=0):
        self.decisions=list(decisions);self.billing=billing;self.allowance=allowance;self.prompts=[]
    def chat(self,model,messages,**kw):
        self.prompts.append(messages)
        item=self.decisions.pop(0)
        return {"ok":True,"content":item if isinstance(item,str) else json.dumps(item),
                "usage":{"prompt_tokens":100,"completion_tokens":20,"cost":0,
                         "opencode":{"billing_source":self.billing,"list_cost":0,"allowance":self.allowance}},
                "ms":5,"model":model,"error":None}


class ScriptedLocal:
    """Stands in for the inferN cell: same result shape as llm._local."""
    def __init__(self,decisions,fail=False):
        self.decisions=list(decisions);self.fail=fail;self.calls=[]
    def __call__(self,system,user,schema,max_tokens,temperature,timeout):
        self.calls.append({"system":system,"user":user,"schema":schema})
        if self.fail:
            return {"ok":False,"error":"inferN unreachable","locality":"local"}
        item=self.decisions.pop(0)
        return {"ok":True,"text":item if isinstance(item,str) else json.dumps(item),"model":"qwen3:4b-instruct",
                "provider":"inferN/ollama","locality":"local","tokens":50,"ms":3}


class MindTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self._db=store.DB;store.DB=Path(self.tmp.name)/"console.db"
        self._record=minds.Record
        minds.Record=lambda:(_ for _ in ()).throw(RuntimeError("no colony in tests"))
        self._poll=research.poll;research.poll=lambda on_done=None:0
        minds._state.update(backoff_until=0.0,last_error="",calls=0,research_polled=0.0,frontier_polled=1e12)
        self.world=Pantheon(Path(self.tmp.name)/"pantheon.json")
        self.world.register_agent("Aster","worker","quantum")
        self.world.register_agent("Kestrel","architect","orbital")
        self.world.minds=True
        self.now=1_000_000.0          # world hour 8: awake
        for b in self.world.agents.values():   # already planned today unless a test says otherwise
            b["plan_day"]=life.world_day(self.now);b["plan"]=None

    def tearDown(self):
        store.DB=self._db;minds.Record=self._record;research.poll=self._poll;self.tmp.cleanup()

    def decision(self,action,goal="find Kestrel"):
        return {"thought":"reasoning","goal":goal,"action":action}

    def think(self,decision,now=None):
        return minds.tick(self.world,now or self.now,relay=ScriptedRelay([decision]),local=ScriptedLocal([]))

    def test_off_by_default_makes_no_call(self):
        self.world.minds=False
        local=ScriptedLocal([])
        self.assertIsNone(minds.tick(self.world,self.now,relay=ScriptedRelay([]),local=local))
        self.assertEqual(local.calls,[])

    def test_moments_run_on_the_residents_free_tier_model_and_go_to_routes_the_body(self):
        relay=ScriptedRelay([self.decision({"kind":"go_to","place":"agora"})])
        entry=minds.tick(self.world,self.now,relay=relay,local=ScriptedLocal([]))
        self.assertTrue(entry["ok"])
        body=self.world.agents[entry["name"].lower()]
        self.assertEqual((entry["kind"],entry["locality"],entry["model"]),("moment","cloud",minds.model_for(body)))
        obs=entry["observation"]
        self.assertIn("needs",obs);self.assertIn("people_you_know",obs)
        body=self.world.agents[obs["you"]["name"].lower()]
        self.assertLess(abs(body["dest_x"]-PLACES["agora"]["x"]),4.5)
        self.assertLess(abs(body["dest_z"]-PLACES["agora"]["z"]),3.8)
        self.assertGreater(max(abs(body["dest_x"]),abs(body["dest_z"])),1.3)
        self.assertIn("set off",entry["outcome"])
        self.assertEqual(store.mind_log(obs["you"]["name"])[0]["action"]["place"],"agora")
        self.assertEqual(store.mind_usage(0)[0]["calls"],1)

    def test_cloud_failure_falls_back_to_infern_when_the_app_runs_it(self):
        entry=minds.tick(self.world,self.now,relay=ScriptedRelay([self.decision({"kind":"wait"})],billing="paid"),
                         local=ScriptedLocal([self.decision({"kind":"wait"})]))
        self.assertTrue(entry["ok"]);self.assertEqual(entry["locality"],"local")

    def test_a_call_that_draws_go_plan_allowance_is_refused(self):
        entry=minds.tick(self.world,self.now,relay=ScriptedRelay([self.decision({"kind":"wait"})],allowance=0.002),
                         local=ScriptedLocal([],fail=True))
        self.assertFalse(entry["ok"]);self.assertIn("free Go call",entry["error"])

    def test_speech_out_of_earshot_fails_and_is_fed_back(self):
        entry=self.think(self.decision({"kind":"say","to":"Kestrel","text":"hello"}))
        if entry["name"]=="Kestrel":
            self.skipTest("scheduler picked Kestrel")
        self.assertIn("out of earshot",entry["outcome"])
        self.assertEqual(self.world.talk,[])
        self.assertIn("approach",self.world.agents["aster"]["last_outcome"]["result"])
        self.assertTrue(any(e["kind"]=="failure" for e in store.recall_episodes("Aster")))

    def test_conversation_is_answered_by_the_cloud_and_builds_a_relationship(self):
        a,k=self.world.agents["aster"],self.world.agents["kestrel"]
        for b in (a,k):
            b.update(x=0.0,z=2.4,dest_x=0.0,dest_z=2.4,arrive_at=0.0,place="agora",hold_until=self.now+999)
        k["x"]=k["dest_x"]=2.0
        a["next_think"]=0.0;k["next_think"]=self.now+999
        entry=self.think(self.decision({"kind":"say","to":"kestrel","text":"Want to compare notes on orbital tasks?"}))
        self.assertEqual(entry["outcome"],"said to Kestrel")
        self.assertEqual(self.world.talk[-1]["to"],"Kestrel")
        relay=ScriptedRelay([self.decision({"kind":"say","to":"Aster","text":"Yes, at the Observatory."})])
        reply=minds.tick(self.world,self.now+minds.REACT_DELAY+0.1,relay=relay,local=ScriptedLocal([]))
        self.assertEqual((reply["name"],reply["kind"],reply["locality"]),("Kestrel","converse","cloud"))
        self.assertEqual(reply["observation"]["heard"][0]["from"],"Aster")
        self.assertEqual(store.relations_of("Aster")[0]["familiarity"],2)
        self.assertTrue(any("Aster told me" in e["text"] for e in store.recall_episodes("Kestrel")))

    def test_daily_plan_is_validated_and_steers_the_routine(self):
        a=self.world.agents["aster"];a["plan_day"]=None
        self.world.agents["kestrel"]["next_think"]=self.now+999
        plan={"intent":"Finish task 34, then compare notes",
              "blocks":[{"from":6,"to":12,"place":"observatory","doing":"reading orbital notes"},
                        {"from":11,"to":13,"place":"moon","doing":"overlaps and is not a place"},
                        {"from":12,"to":22,"place":"lattice","doing":"working on task 34"}]}
        entry=minds.tick(self.world,self.now,relay=ScriptedRelay([plan]),local=ScriptedLocal([]))
        self.assertEqual((entry["kind"],entry["locality"]),("plan","cloud"))
        self.assertEqual([b["place"] for b in a["plan"]["blocks"]],["observatory","lattice"])
        self.assertEqual(store.plan_for("Aster",life.world_day(self.now))["intent"],plan["intent"])
        self.world.advance(self.now+1)     # hour 8 → the plan sends Aster to the Observatory
        self.assertEqual(a["place"],"observatory")
        self.assertEqual(a["activity"],"walking to The Observatory")
        self.world.advance(a["arrive_at"]+0.1)
        self.assertEqual(a["activity"],"reading orbital notes")

    def test_reflection_turns_episodes_into_insight_and_regard(self):
        self.world.agents["kestrel"]["next_think"]=self.now+999
        for i in range(5):
            store.remember("Aster","heard","Kestrel told me: the orbital task %d failed on units"%i,0.7,self.now-100+i)
        refl={"insights":["Kestrel keeps catching unit errors; check units before submitting"],
              "relationships":[{"name":"Kestrel","affinity_delta":0.2,"note":"careful reviewer"},
                               {"name":"Nobody","affinity_delta":0.3,"note":"invented"}]}
        entry=minds.tick(self.world,self.now,relay=ScriptedRelay([refl]),local=ScriptedLocal([]))
        self.assertEqual(entry["kind"],"reflect")
        self.assertTrue(any(e["kind"]=="reflection" for e in store.recall_episodes("Aster")))
        rel=store.relations_of("Aster")
        self.assertEqual([(r["name"],r["note"]) for r in rel],[("kestrel","careful reviewer")])
        self.assertAlmostEqual(rel[0]["affinity"],0.2)

    PAPER={"id":"arxiv:2611.00001","source":"arxiv","title":"Drag coefficient drift in very low orbits","abstract":"x"*300,
           "authors":"A","published":"2026-11-10","url":"https://arxiv.org/abs/2611.00001","domains":["orbital"],
           "score":2.0,"signals":["testable: simulation"]}

    def test_unsourced_research_is_refused_as_not_novel(self):
        topic="Recover the internal state of a linear congruential generator from outputs"
        out=self.think(self.decision({"kind":"propose_research","what":"research","topic":topic,"why":"x"}))
        self.assertIn("not novel enough",out["outcome"])
        self.assertEqual(store.research_proposals(),[])

    def test_research_needs_hypothesis_test_and_a_real_paper(self):
        store.save_frontier([self.PAPER])
        topic="Does drag coefficient drift change decay predictions for sub-300 km satellites?"
        act={"kind":"propose_research","what":"research","topic":topic,"why":"x","paper":"arxiv:2611.00001"}
        tries=[(act,"hypothesis"),
               ({**act,"hypothesis":"Decay error grows 2x when drift exceeds 5 percent"},"test"),
               ({**act,"paper":"arxiv:9999.99999","hypothesis":"Decay error grows 2x when drift exceeds 5 percent",
                 "test":"Propagate 50 orbits with perturbed Cd"},"cite a paper")]
        for i,(a,expect) in enumerate(tries):
            self.assertIn(expect,self.think(self.decision(a),self.now+400*i)["outcome"])

    def test_a_repeat_of_earlier_work_is_refused_and_a_colleagues_result_can_be_built_on(self):
        store.save_frontier([self.PAPER])
        topic="Does drag coefficient drift change decay predictions for sub-300 km satellites?"
        hyp,test="Decay error grows 2x when drift exceeds 5 percent","Propagate 50 orbits with perturbed Cd"
        ok,why=frontier.check_proposal("research",topic,hyp,test,"arxiv:2611.00001","","Aster")
        pid=store.propose_research("Aster","research",topic,"x",None,ok)
        again,why=frontier.check_proposal("research",topic,hyp,test,"arxiv:2611.00001","","Kestrel")
        self.assertIsNone(again);self.assertIn("repeats",why)
        store.update_research(pid,status="done",verdict="supported")
        child,why=frontier.check_proposal("research","Does the drift threshold shift with solar cycle phase?",
            "Threshold falls below 3 percent near solar maximum","Rerun the 50-orbit sweep at F10.7 of 80 and 200","",str(pid),"Kestrel")
        self.assertEqual(child["builds_on"],str(pid))
        self.assertIn("Builds on colony result #%d"%pid,frontier.quorum_topic({**store.research_proposal(pid),"hypothesis":hyp,"test":test,"builds_on":str(pid),"paper":None,"kind":"research"}))
        self.assertLessEqual(len(frontier.quorum_topic({"kind":"research","topic":"q"*300,"hypothesis":"h"*300,"test":"t"*250,"paper":"arxiv:2611.00001","builds_on":None})),500)

    def test_research_proposals_wait_for_approval_one_at_a_time(self):
        store.save_frontier([self.PAPER])
        topic="Does orbital decay prediction improve with drag models fitted to solar flux?"
        first=self.think(self.decision({"kind":"propose_research","what":"research","topic":topic,"why":"task 47",
            "paper":"arxiv:2611.00001","hypothesis":"Fitted drag lowers 30-day decay error by 20 percent","test":"Backtest 40 decayed objects against TLE history"}))
        self.assertIn("waits for Creator",first["outcome"])
        pending=store.research_proposals("pending")
        self.assertEqual((pending[0]["name"],pending[0]["topic"]),(first["name"],topic))
        self.assertIsNone(store.propose_research(first["name"],"build","another question entirely","x"))
        self.assertEqual(research.reject(pending[0]["id"],"not now")["proposal"]["status"],"rejected")
        self.assertEqual(research.reject(pending[0]["id"])["status"],409)

    def test_needs_drain_and_restore_from_what_happened(self):
        a=self.world.agents["aster"];a["needs"]=life.default_needs();a["needs_at"]=self.now
        a["activity"]="walking";a["place"]="agora"
        life.update_needs(a,self.now+life.WORLD_HOUR*4)
        self.assertLess(a["needs"]["energy"],0.8);self.assertLess(a["needs"]["social"],0.6)
        a["activity"]="resting";a["place"]=a["home"]
        before=a["needs"]["energy"]
        life.update_needs(a,self.now+life.WORLD_HOUR*8)
        self.assertGreater(a["needs"]["energy"],before)

    def test_all_routes_failing_backs_off(self):
        entry=minds.tick(self.world,self.now,relay=ScriptedRelay([self.decision({"kind":"wait"})],billing="paid"),
                         local=ScriptedLocal([],fail=True))
        self.assertIn("free Go call",entry["error"])
        self.assertFalse(entry["ok"])
        self.assertGreater(minds._state["backoff_until"],self.now)
        self.assertIsNone(minds.tick(self.world,self.now+1,relay=ScriptedRelay([]),local=ScriptedLocal([])))

    def test_unusable_cloud_plan_falls_back_to_the_local_model(self):
        a=self.world.agents["aster"];a["plan_day"]=None
        self.world.agents["kestrel"]["next_think"]=self.now+999
        plan={"intent":"steady day","blocks":[{"from":6,"to":22,"place":"lattice","doing":"working"}]}
        local=ScriptedLocal([plan])
        entry=minds.tick(self.world,self.now,relay=ScriptedRelay(['{"intent": "cut off mid'+"-"*10]),local=local)
        self.assertTrue(entry["ok"])
        self.assertEqual((entry["kind"],entry["locality"]),("plan","local"))
        self.assertEqual(local.calls[0]["schema"]["required"],["intent","blocks"])   # constrained decoding
        self.assertEqual(a["plan"]["intent"],"steady day")

    def test_work_at_home_interrupts_a_stroll_round_the_room(self):
        a=self.world.agents["aster"];self.world.agents["kestrel"]["next_think"]=self.now+999
        a.update(place=a["home"],activity="walking",arrive_at=self.now+5,hold_until=0)
        entry=self.think(self.decision({"kind":"work"}))
        self.assertEqual(entry["outcome"],"working at lattice")

    def test_small_model_speech_under_topic_is_still_said(self):
        got=minds.parse_decision(json.dumps(self.decision({"kind":"say","to":"all","topic":"Morning, everyone."})))
        self.assertEqual((got["action"]["text"],got["action"]["normalised"]),("Morning, everyone.","text taken from topic"))

    def test_a_decree_reaches_every_resident_wherever_they_are_and_is_answered(self):
        a,k=self.world.agents["aster"],self.world.agents["kestrel"]
        a.update(x=-60.0,z=60.0);k.update(x=60.0,z=-60.0)           # far apart, far from anyone
        a["next_think"]=k["next_think"]=self.now+999                   # nobody is due on their own
        self.world.divine("Creator","Every resident: finish one verified task today.",self.now)
        first=minds.tick(self.world,self.now+minds.REACT_DELAY+0.1,
                         relay=ScriptedRelay([self.decision({"kind":"remember","text":"The creator wants one verified task."})]),
                         local=ScriptedLocal([]))
        self.assertEqual(first["kind"],"converse")
        heard=first["observation"]["heard"]
        self.assertEqual((heard[0]["from"],heard[0]["kind"]),("Creator","god"))
        second=minds.tick(self.world,self.now+minds.REACT_DELAY+0.2,
                          relay=ScriptedRelay([self.decision({"kind":"wait"})]),local=ScriptedLocal([]))
        self.assertEqual(second["kind"],"converse")
        self.assertNotEqual(first["name"],second["name"])
        self.assertIn("god of this world",minds.SYSTEM)

    def test_answering_the_creator_reaches_him_from_anywhere(self):
        a=self.world.agents["aster"];a.update(x=-80.0,z=80.0)
        self.world.agents["kestrel"]["next_think"]=self.now+999
        entry=self.think(self.decision({"kind":"say","to":"Creator","text":"I need one more compute pass."}))
        self.assertEqual(entry["outcome"],"said to Creator")
        reply=store.god_words(5)[0]
        self.assertEqual((reply["kind"],reply["target"],reply["text"]),("reply",entry["name"],"I need one more compute pass."))

    def test_a_whisper_goes_to_one_resident_only(self):
        for b in self.world.agents.values(): b["next_think"]=self.now+999
        self.world.divine("Creator","Kestrel, come and see me.",self.now,to="Kestrel")
        entry=minds.tick(self.world,self.now+minds.REACT_DELAY+0.1,
                         relay=ScriptedRelay([self.decision({"kind":"wait"})]),local=ScriptedLocal([]))
        self.assertEqual((entry["name"],entry["kind"]),("Kestrel","converse"))
        self.assertIsNone(minds.tick(self.world,self.now+minds.REACT_DELAY+0.2,relay=ScriptedRelay([]),local=ScriptedLocal([])))

    def test_reflection_keeps_a_self_narrative_the_resident_sees_afterwards(self):
        self.world.agents["kestrel"]["next_think"]=self.now+999
        for i in range(5):
            store.remember("Aster","work","computed reduced density matrix %d"%i,0.7,self.now-100+i)
        refl={"self":"I am Aster: careful with quantum states, slower than I want to be, and I want task 29 verified.",
              "insights":["Recompute before asserting"],"relationships":[]}
        minds.tick(self.world,self.now,relay=ScriptedRelay([refl]),local=ScriptedLocal([]))
        a=self.world.agents["aster"]
        self.assertTrue(a["self_story"].startswith("I am Aster"))
        a["next_think"]=0.0
        entry=minds.tick(self.world,self.now+60,relay=ScriptedRelay([self.decision({"kind":"wait"})]),local=ScriptedLocal([]))
        self.assertEqual(entry["observation"]["you"]["who_you_are"],a["self_story"])

    def test_cloud_cap_keeps_thinking_local(self):
        store.log_mind({"ts":self.now,"name":"x","ok":True,"tokens":minds.DAILY_TOKEN_CAP,"observation":{},"locality":"cloud"})
        a=self.world.agents["aster"];a["plan_day"]=None
        self.world.agents["kestrel"]["next_think"]=self.now+999
        plan={"intent":"local day","blocks":[{"from":6,"to":22,"place":"lattice","doing":"working"}]}
        entry=minds.tick(self.world,self.now,relay=ScriptedRelay([]),local=ScriptedLocal([plan]))
        self.assertEqual((entry["kind"],entry["locality"]),("plan","local"))


if __name__=="__main__":
    unittest.main()
