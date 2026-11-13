export const width = 640;
export const height = 360;
const shipY = 304;
const finish = 28;
export const beaconGoal = 4;
export const segments = ["潮汐入口","逆风带","港口回线"];
const schedule = [
  [0,320,"beacon"],[1.3,170,"debris"],[2.1,470,"debris"],[3.4,435,"beacon"],[4.6,280,"debris"],
  [6.1,190,"beacon"],[7.1,352,"debris"],[8.3,480,"debris"],[9.6,375,"beacon"],[10.5,165,"debris"],
  [11.7,485,"beacon"],[12.2,260,"debris"],[13.2,350,"debris"],[14,220,"beacon"],[14.6,453,"debris"],
  [16,530,"debris"],[16.6,410,"beacon"],[17.2,215,"debris"],[18.6,126,"beacon"],[19,323,"debris"],
  [20.1,453,"beacon"],[20.7,229,"debris"],[21.6,359,"debris"],[22.7,286,"beacon"],[23.7,508,"debris"],
  [24.4,485,"beacon"],[24.8,181,"debris"],[25.3,375,"debris"],
] as const;

type Item = {x:number;y:number;kind:"beacon"|"debris"};
type Phase = "ready"|"playing"|"paused"|"won"|"lost";
export type Flight = ReturnType<typeof newFlight>;

export function newFlight() {
  return {time:0,x:width/2,shield:3,beacons:0,flashUntil:0,next:0,items:[] as Item[],phase:"ready" as Phase};
}

export const section = (time: number) => time < 9 ? 0 : time < 18 ? 1 : 2;
export const progress = (time: number) => Math.min(100,Math.floor(time/finish*100));

export function advance(flight:Flight, dt:number, target:number): Flight {
  const time = Math.min(finish,flight.time+dt);
  const speed = 126+section(time)*35;
  const x = flight.x + (Math.max(25,Math.min(width-25,target))-flight.x)*Math.min(dt*11,1);
  let {next,shield,beacons,flashUntil} = flight;
  const items = flight.items.map(item=>({...item,y:item.y+dt*speed}));
  while (next<schedule.length && schedule[next][0]<=time) {
    const [,x,kind] = schedule[next++];
    items.push({x,y:-14,kind});
  }
  const onScreen = items.filter(item=>{
    if (item.y > height+25) return false;
    if (Math.abs(item.y-shipY)>24 || Math.abs(item.x-x)>(item.kind==="beacon"?27:31)) return true;
    if (item.kind==="beacon") beacons++;
    else if (flashUntil<=time) {shield--;flashUntil=time+.65;}
    return false;
  });
  const phase = shield<=0 ? "lost" : time===finish ? (beacons>=beaconGoal ? "won" : "lost") : "playing";
  return {time,x,shield,beacons,flashUntil,next,items:onScreen,phase};
}

export function drawFlight(ctx:CanvasRenderingContext2D, flight:Flight) {
  const backdrop = ctx.createLinearGradient(0,0,0,height);
  backdrop.addColorStop(0,"#0d1030");backdrop.addColorStop(.53,"#13334f");backdrop.addColorStop(1,"#171d45");
  ctx.fillStyle=backdrop;ctx.fillRect(0,0,width,height);
  const glow = ctx.createRadialGradient(width*.76,height*.36,0,width*.76,height*.36,width*.5);
  glow.addColorStop(0,"#2d637dba");glow.addColorStop(1,"#17264b00");
  ctx.fillStyle=glow;ctx.fillRect(0,0,width,height);

  ctx.strokeStyle="#5cb8d538";ctx.lineWidth=1;
  for(let i=1;i<7;i++){
    const x=(i*width)/7;
    ctx.beginPath();ctx.moveTo(width/2+(x-width/2)*.52,0);ctx.lineTo(x,height);ctx.stroke();
  }
  for(let y=-24+flight.time*105%30;y<height;y+=30){
    ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(width,y);ctx.stroke();
  }
  ctx.fillStyle="#92cce99e";
  for(let i=0;i<36;i++){
    const x=(i*127+38)%width,y=(i*47+flight.time*(32+i%5*8))%height;
    ctx.fillRect(x,y,i%4===0?2:1,i%4===0?8:4);
  }
  for(const item of flight.items){
    ctx.save();ctx.translate(item.x,item.y);
    if(item.kind==="beacon"){
      ctx.strokeStyle="#80fff2";ctx.shadowColor="#69ffe5";ctx.shadowBlur=15;ctx.lineWidth=2;
      ctx.beginPath();ctx.moveTo(0,-14);ctx.lineTo(10,0);ctx.lineTo(0,14);ctx.lineTo(-10,0);ctx.closePath();ctx.stroke();
      ctx.fillStyle="#c2fff7";ctx.fillRect(-2,-2,4,4);
    }else{
      ctx.fillStyle="#67395b";ctx.strokeStyle="#ef9f8a";ctx.lineWidth=2;
      ctx.beginPath();ctx.moveTo(-24,6);ctx.lineTo(-15,-13);ctx.lineTo(13,-18);ctx.lineTo(26,0);ctx.lineTo(14,16);ctx.lineTo(-14,15);ctx.closePath();ctx.fill();ctx.stroke();
      ctx.strokeStyle="#b86873";ctx.beginPath();ctx.moveTo(-15,-13);ctx.lineTo(4,3);ctx.lineTo(26,0);ctx.moveTo(4,3);ctx.lineTo(14,16);ctx.stroke();
    }
    ctx.restore();
  }
  ctx.save();ctx.translate(flight.x,shipY);
  const trail=ctx.createLinearGradient(0,5,0,48);
  trail.addColorStop(0,"#6cfdec");trail.addColorStop(1,"#6cfded00");
  ctx.fillStyle=trail;ctx.beginPath();ctx.moveTo(-7,8);ctx.lineTo(7,8);ctx.lineTo(1,49);ctx.closePath();ctx.fill();
  ctx.fillStyle=flight.flashUntil>flight.time?"#ff9e97":"#d0f5ff";
  ctx.strokeStyle="#59dff9";ctx.lineWidth=1.5;ctx.shadowColor="#76dffc";ctx.shadowBlur=17;
  ctx.beginPath();ctx.moveTo(0,-22);ctx.lineTo(23,13);ctx.lineTo(8,7);ctx.lineTo(0,13);ctx.lineTo(-8,7);ctx.lineTo(-23,13);ctx.closePath();ctx.fill();ctx.stroke();
  ctx.fillStyle="#3271a1";ctx.beginPath();ctx.moveTo(0,-14);ctx.lineTo(5,0);ctx.lineTo(-5,0);ctx.closePath();ctx.fill();ctx.restore();
}
