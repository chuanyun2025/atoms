export const sectors = [
  {name:"中继站", charge:19, map:[
    "#########",
    "#S..*...#",
    "#.##.##.#",
    "#....+..#",
    "###.#.#.#",
    "#*....#E#",
    "#########",
  ]},
  {name:"磁暴回廊", charge:21, map:[
    "#########",
    "#S.~.*#E#",
    "#.##..#.#",
    "#.*+~...#",
    "#.###.#.#",
    "#...~.*.#",
    "#########",
  ]},
  {name:"远端信标", charge:22, map:[
    "#########",
    "#S..#...#",
    "#.#.*.#E#",
    "#~#.#~#.#",
    "#...+.*.#",
    "#*..#~..#",
    "#########",
  ]},
];

export const vectors = {ArrowUp:[0,-1],ArrowDown:[0,1],ArrowLeft:[-1,0],ArrowRight:[1,0]} as const;
export type Direction = keyof typeof vectors;
export type Mission = ReturnType<typeof loadSector>;

export function loadSector(index = 0, previousMoves = 0) {
  const sector = sectors[index];
  const y = sector.map.findIndex(row => row.includes("S"));
  return {
    index,x:sector.map[y].indexOf("S"),y,energy:sector.charge,
    moves:0,previousMoves,relays:0,required:sector.map.join("").split("*").length-1,
    used:[] as string[], phase:"ready" as "ready"|"playing"|"paused"|"clear"|"won"|"lost",
    message:"接通信标后，前往出口。",
  };
}

export function step(mission: Mission, direction: Direction): Mission {
  if (mission.phase !== "playing") return mission;
  const [dx,dy] = vectors[direction];
  const x = mission.x+dx, y = mission.y+dy;
  const tile = sectors[mission.index].map[y]?.[x] ?? "#";
  if (tile === "#") return {...mission,message:"前方是隔离墙，选择另一条路线。"};

  const cell = x+":"+y;
  const fresh = !mission.used.includes(cell);
  const relay = tile === "*" && fresh;
  const charge = tile === "+" && fresh;
  const relays = mission.relays + Number(relay);
  const energy = Math.max(0, mission.energy - (tile === "~" ? 3 : 1) + (charge ? 7 : 0));
  const escaped = tile === "E" && relays === mission.required;
  const phase = escaped ? (mission.index === sectors.length-1 ? "won" : "clear") : energy === 0 ? "lost" : "playing";
  const message = escaped ? "出口已开启，信标传输完成。" : phase === "lost" ? "电量耗尽，重开可尝试更短路线。" :
    relay ? "信标已接通。" : charge ? "补给已吸收，获得 7 格电量。" :
    tile === "~" ? "磁暴区消耗 3 格电量。" : tile === "E" ? "出口锁定，先接通全部信标。" : "普通移动消耗 1 格电量。";
  return {...mission,x,y,energy,relays,phase,message,moves:mission.moves+1,
    used:relay||charge ? [...mission.used,cell] : mission.used};
}
