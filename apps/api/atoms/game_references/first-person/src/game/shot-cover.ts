import { Ray, Vector3, type Box3 } from "three";

/** Clip a shot to the first solid volume on its finite world-space path. */
export function clipShotToCover(origin: Vector3, target: Vector3, solids: readonly Box3[]) {
  const direction = target.clone().sub(origin);
  let distance = direction.length();
  let point = target.clone();
  let blocked = false;
  if (distance === 0) return { point, distance, blocked };

  const ray = new Ray(origin, direction.divideScalar(distance));
  const intersection = new Vector3();
  for (const solid of solids) {
    if (solid.isEmpty()) continue;
    if (solid.containsPoint(origin)) {
      return { point: origin.clone(), distance: 0, blocked: true };
    }
    if (!ray.intersectBox(solid, intersection)) continue;
    const entryDistance = origin.distanceTo(intersection);
    if (entryDistance <= distance) {
      point.copy(intersection);
      distance = entryDistance;
      blocked = true;
    }
  }
  return { point, distance, blocked };
}
