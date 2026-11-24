"""Rule-based, evidence-backed world generation from the colony's real record.

Artifacts and new collaboration spaces live in the console-owned store. The colony DB is
only read. No model call is used to invent state: a workboard mirrors task/tool/memory rows,
and a shared pavilion appears after repeated saved meetings between the same pair.
"""
from __future__ import annotations

import hashlib
import math
import time

import store
from bridge import Record, affect_for
from pantheon import PLACES

DOMAIN_HUE={"quantum":262,"orbital":42,"climate":176,"cyber":142,"world":320,"brief":210}


def refresh(record: Record | None=None) -> dict:
    record=record or Record()
    now=time.time()
    agents=record.q("SELECT * FROM agents WHERE status!='retired' ORDER BY name")
    for agent in agents:
        task=record.one("SELECT id,domain,difficulty,question,reward,claimed_tick FROM tasks "
                        "WHERE status='claimed' AND claimed_by=? ORDER BY id DESC",(agent["id"],))
        tools=record.q("SELECT tick,name,args,result FROM instruments WHERE agent_id=? ORDER BY id DESC LIMIT 4",
                       (agent["id"],))
        memories=record.q("SELECT id,tick,kind,text,salience FROM memory WHERE agent_id=? ORDER BY id DESC LIMIT 3",
                          (agent["id"],))
        latest=record.one("SELECT id,tick,kind,text FROM events WHERE agent_id=? ORDER BY id DESC",(agent["id"],))
        content={
            "ci":agent["name"],"tier":agent["tier"],"domain":agent["domain"],
            "home":agent["domain"],"status":agent["status"],
            "task":task,"tools":tools,"recent_memory":memories,
            "latest_event":latest,"affect":affect_for(agent,task),
            "generated_from":"colony record; no model-invented facts",
        }
        store.upsert_world_artifact({
            "id":"workboard:%s"%agent["id"],"owner":agent["name"],"kind":"workboard",
            "title":agent["name"]+" · live workboard",
            "source_ref":"agent:%s/task:%s"%(agent["id"],task["id"] if task else "none"),
            "content":content,
        })

    # Repeated meetings signal a sustained collaboration need; create one persistent
    # pavilion for that pair, at a deterministic unoccupied edge of the current town.
    for pair in store.collaboration_pairs(min_meetings=2):
        names=pair["participants"]
        left,right=names[0],names[1]
        key="%s|%s"%(left.lower(),right.lower())
        digest=hashlib.sha256(key.encode("utf-8")).digest()
        slug="-".join("".join(c.lower() if c.isalnum() else "-" for c in n).strip("-") for n in names)
        place_id="salon-"+slug
        existing=next((p for p in store.world_places() if p["id"]==place_id),None)
        if existing:
            x,z=float(existing["x"]),float(existing["z"])
        else:
            start=(int.from_bytes(digest[:4],"big")/(2**32))*2*math.pi
            radius=23.5+(digest[4]%2)*1.5
            occupied=[(float(p["x"]),float(p["z"])) for p in PLACES.values()]
            occupied.extend((float(p["x"]),float(p["z"])) for p in store.world_places())
            x=z=0.0
            for step in range(48):
                angle=start+step*2.399963229728653
                candidate=(round(math.cos(angle)*radius,2),round(math.sin(angle)*radius,2))
                if all(math.hypot(candidate[0]-ox,candidate[1]-oz)>=9.0 for ox,oz in occupied):
                    x,z=candidate;break
            else:
                x,z=round(math.cos(start)*22.5,2),round(math.sin(start)*22.5,2)
        records=[record.agent_by_name(name) for name in names]
        hues=[DOMAIN_HUE.get((a or {}).get("domain"),210) for a in records]
        hue=int(sum(hues)/len(hues)) if hues else 210
        store.upsert_world_place({
            "id":place_id,"name":left+" & "+right+" · collaboration pavilion",
            "kind":"social","x":x,"z":z,"hue":hue,"dynamic":True,
            "reason":"Generated after %d saved shared meetings; latest topic: %s"%
                    (pair["interactions"],pair.get("topic") or "conversation"),
            "participants":names,"interactions":pair["interactions"],
        })
    return {"artifacts":store.world_artifacts(100),"places":store.world_places()}
