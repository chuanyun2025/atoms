import { CatmullRomCurve3, Vector3 } from "three";

export const course = {
  id: "red-bay-circuit",
  title: "赤湾巡回赛",
  circuit: "海岸环线",
  scene: { sky: 0xefaf91, ground: 0x61585a, haze: 0xefaf91, car: 0x3addcd, curb: 0xff663d },
  points: [[0, 0], [0, 49], [29, 91], [82, 106], [132, 82], [139, 26], [104, -16], [44, -37]],
};

export const track = new CatmullRomCurve3(course.points.map(([x, z]) => new Vector3(x, 0, z)), true, "centripetal");
track.arcLengthDivisions = 600;
export const length = track.getLength();
export const roadHalfWidth = 6.4;
export const driveLimit = roadHalfWidth - 0.82;
export const gates = [0.16, 0.36, 0.6, 0.81, 1].map(fraction => fraction * length);
export const features = [
  {kind: "charge", fraction: 0.023, lane: 0},
  {kind: "barrier", fraction: 0.063, lane: 0},
  {kind: "charge", fraction: 0.143, lane: -3.2},
  {kind: "barrier", fraction: 0.232, lane: 3.2},
  {kind: "charge", fraction: 0.325, lane: 3.2},
  {kind: "barrier", fraction: 0.42, lane: -3.2},
  {kind: "charge", fraction: 0.52, lane: 0},
  {kind: "barrier", fraction: 0.65, lane: 0},
  {kind: "charge", fraction: 0.74, lane: -3.2},
  {kind: "barrier", fraction: 0.865, lane: 3.2},
] as const;

export function trackFrame(distance: number, lane = 0) {
  const u = ((distance % length) + length) % length / length;
  const point = track.getPointAt(u);
  const heading = track.getTangentAt(u);
  // The chase camera looks along heading. Its right axis is heading × up.
  const right = new Vector3(-heading.z, 0, heading.x);
  return {point: point.addScaledVector(right, lane), heading, right};
}
