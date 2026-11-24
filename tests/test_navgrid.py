import math
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))

import cityplan
import navgrid
from pantheon import PLACES, Pantheon

RESIDENTS=[{"name":n,"home":h} for n,h in [("Aster","lattice"),("Vesper","lattice"),("Kestrel","observatory"),
                                           ("Fathom","conservatory"),("Morrow","foundry"),("Tessellate","study")]]
ASSETS=([{"id":"b%d"%i,"kind":"building","x":0,"z":0,"width":18 if i%3==0 else 10,"depth":14 if i%3==0 else 8,
          "height":8,"created":i} for i in range(12)]+
        [{"id":"f%d"%i,"kind":"street_furniture","x":0,"z":0,"width":2.4,"depth":0.8,"height":1,"created":100+i}
         for i in range(40)]+
        [{"id":"car","kind":"car","x":0,"z":0,"width":1.8,"depth":3.2,"height":1.4,"created":200},
         {"id":"park","kind":"park","x":0,"z":0,"width":14,"depth":12,"height":1,"created":201}])


def fixed():
    return [dict(v,id=k) for k,v in PLACES.items()]


def hit(x,z,c):
    if c["type"]=="box":
        return c["x0"]<=x<=c["x1"] and c["z0"]<=z<=c["z1"]
    return math.hypot(x-c["x"],z-c["z"])<c["r"]


def rect(x,z,w,d,yaw_or_facing):
    turned=yaw_or_facing in ("+x","-x") or (isinstance(yaw_or_facing,float) and abs(math.sin(yaw_or_facing))>0.5)
    if turned: w,d=d,w
    return (x-w/2,z-d/2,x+w/2,z+d/2)


class PlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lay=navgrid.layout(fixed(),[],ASSETS,RESIDENTS)
        cls.grid=navgrid.NavGrid(cls.lay)

    def test_plan_is_deterministic(self):
        self.assertEqual(navgrid.layout(fixed(),[],ASSETS,RESIDENTS),self.lay)

    def test_every_asset_is_sited_and_nothing_overlaps_or_sits_on_a_road(self):
        self.assertEqual({s["id"] for s in self.lay["sited"]},{a["id"] for a in ASSETS})
        by={a["id"]:a for a in ASSETS}
        rects=[]
        for s in self.lay["sited"]:
            a=by[s["id"]]
            rects.append((s["id"],rect(s["x"],s["z"],s.get("w",a["width"]),s.get("d",a["depth"]),s["yaw"])))
        rects+=[(h["id"],rect(h["x"],h["z"],h["width"],h["depth"],h["facing"])) for h in self.lay["houses"]]
        for i,(na,a) in enumerate(rects):
            for nb,b in rects[i+1:]:
                self.assertFalse(a[0]<b[2] and b[0]<a[2] and a[1]<b[3] and b[1]<a[3],(na,nb))
            if na=="car":
                continue
            for x in (a[0],a[2],(a[0]+a[2])/2):
                for z in (a[1],a[3],(a[1]+a[3])/2):
                    d,road=cityplan.road_dist(x,z,self.lay["roads"])
                    self.assertGreater(d,road["width"]/2,(na,road["id"]))

    def test_each_resident_has_a_house_and_a_desk_at_its_workplace(self):
        self.assertEqual(sorted(h["owner"] for h in self.lay["houses"]),sorted(r["name"] for r in RESIDENTS))
        for w in self.lay["workstations"]:
            home=next(r["home"] for r in RESIDENTS if r["name"]==w["name"])
            self.assertEqual(w["place"],home)
            p=PLACES[home]
            self.assertLess(abs(w["chair"][0]-p["x"]),cityplan.BUILDING_W/2)
            self.assertLess(abs(w["chair"][1]-p["z"]),cityplan.BUILDING_D/2)
            self.assertTrue(self.grid.free(*w["chair"]))

    def test_trees_and_lamps_stay_off_carriageways(self):
        for t in self.lay["trees"]+self.lay["lamps"]:
            d,road=cityplan.road_dist(t["x"],t["z"],self.lay["roads"])
            self.assertGreater(d,road["width"]/2,(t,road["id"]))

    def test_pedestrians_never_walk_on_the_highway(self):
        self.assertFalse(self.grid.free(cityplan.HW,0.0))
        self.assertFalse(self.grid.free(0.0,-cityplan.HW))

    def assert_walkable(self,path):
        for a,b in zip(path,path[1:]):
            L=math.hypot(b[0]-a[0],b[1]-a[1]);n=max(1,int(L/0.1))
            for s in range(n+1):
                x=a[0]+(b[0]-a[0])*s/n;z=a[1]+(b[1]-a[1])*s/n
                for c in self.lay["colliders"]:
                    self.assertFalse(hit(x,z,c),"path point (%.2f,%.2f) inside %s"%(x,z,c))

    def test_commute_from_desk_to_house_avoids_every_solid(self):
        for r in RESIDENTS[:3]:
            desk=next(w for w in self.lay["workstations"] if w["name"]==r["name"])
            house=next(h for h in self.lay["houses"] if h["owner"]==r["name"])
            path=self.grid.route(desk["chair"],(house["x"],house["z"]))
            self.assertGreater(navgrid.path_length(path),40)
            self.assert_walkable(path)

    def test_leaving_a_building_uses_its_front_door(self):
        hx,hz=PLACES["lattice"]["x"],PLACES["lattice"]["z"]
        path=self.grid.route((hx,hz+1.0),(hx,hz-14.0))
        front=hz+navgrid.BUILDING_D/2
        xs=[]
        for a,b in zip(path,path[1:]):
            if (a[1]-front)*(b[1]-front)<0:
                t=(front-a[1])/(b[1]-a[1]);x=a[0]+(b[0]-a[0])*t
                if abs(x-hx)<navgrid.BUILDING_W/2: xs.append(x)
        self.assertEqual(len(xs),1)
        self.assertLess(abs(xs[0]-hx),navgrid.DOOR_HALF)

    def test_buildings_block_and_parks_do_not(self):
        b=next(s for s in self.lay["sited"] if s["id"]=="b1")
        park=next(s for s in self.lay["sited"] if s["id"]=="park")
        self.assertFalse(self.grid.free(b["x"],b["z"]))
        self.assertTrue(self.grid.free(park["x"],park["z"]))


class BodyTests(unittest.TestCase):
    def test_residents_go_home_to_their_own_house_at_night(self):
        with tempfile.TemporaryDirectory() as tmp:
            world=Pantheon(Path(tmp)/"p.json")
            world.register_agent("Aster","worker","quantum")
            night=1200.0*1000+1200.0*(23/24)           # world hour 23
            world.advance(night)
            body=world.agents["aster"]
            house=world.house_of("Aster")
            self.assertEqual(body["place"],house["id"])
            self.assertEqual(body["activity"],"walking to Aster's house")
            world.advance(body["arrive_at"]+0.1)
            self.assertEqual(body["activity"],"at home")
            self.assertLess(math.hypot(body["x"]-house["x"],body["z"]-house["z"]),3)
            self.assertIn("houses",world.snapshot(body["arrive_at"]+0.1)["layout"])


if __name__=="__main__":
    unittest.main()
