import {expect,it} from "vitest";
import {advance,newFlight,type Flight} from "./flight";

it("allows a full win by steering to incoming beacons",()=>{
  let flight:Flight={...newFlight(),phase:"playing"};
  for(let i=0;i<1800&&flight.phase==="playing";i++){
    const incoming=flight.items.filter(item=>item.kind==="beacon"&&item.y>140&&item.y<310)
      .sort((a,b)=>b.y-a.y)[0];
    flight=advance(flight,1/60,incoming?.x??flight.x);
  }
  expect(flight.phase).toBe("won");
  expect(flight.beacons).toBeGreaterThanOrEqual(4);
  expect(flight.shield).toBeGreaterThan(0);
});

it("fails the mission at the finish when there are too few beacons",()=>{
  let flight:Flight={...newFlight(),phase:"playing"};
  for(let i=0;i<1800&&flight.phase==="playing";i++) flight=advance(flight,1/60,320);
  expect(flight.phase).toBe("lost");
  expect(flight.beacons).toBe(1);
});
