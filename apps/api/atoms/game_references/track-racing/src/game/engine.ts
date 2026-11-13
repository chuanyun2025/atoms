import { driveLimit, features, gates, length } from "./track";

export type Phase = "ready" | "playing" | "paused" | "won";
export type DriveInput = "gas" | "brake" | "left" | "right" | "boost";

export class Race {
  phase: Phase = "ready";
  distance = 0;
  speed = 0;
  lateral = 0;
  steering = 0;
  energy = 0;
  checkpoint = 0;
  collected = 0;
  impacts = 0;
  actions = 0;
  seconds = 0;
  notice = "";
  noticeTime = 0;
  boosting = false;
  passed = new Set<number>();
  held = new Set<DriveInput>();

  setInput(input: DriveInput, down: boolean) {
    if (!down) this.held.delete(input);
    else if (this.phase === "playing" && !this.held.has(input)) {
      this.held.add(input);
      this.actions++;
    }
  }

  pause() {
    if (this.phase === "playing") this.phase = "paused";
    this.held.clear();
  }

  step(dt: number) {
    if (this.phase !== "playing") return;
    this.seconds += dt;
    this.noticeTime = Math.max(0, this.noticeTime - dt);
    const targetSteering = Number(this.held.has("right")) - Number(this.held.has("left"));
    this.steering += (targetSteering - this.steering) * Math.min(1, dt * 8);
    this.boosting = this.held.has("boost") && this.energy > 0 && this.held.has("gas");
    if (this.boosting) this.energy = Math.max(0, this.energy - dt * 30);
    const braking = this.held.has("brake");
    const acceleration = braking ? -29 : this.held.has("gas") ? (this.boosting ? 30 : 17) : -6;
    this.speed = Math.max(0, Math.min(this.boosting ? 44 : 34, this.speed + acceleration * dt));

    const nextLateral = this.lateral + this.steering * (2.1 + this.speed * 0.19) * dt;
    this.lateral = Math.max(-driveLimit, Math.min(driveLimit, nextLateral));
    if (nextLateral !== this.lateral) this.speed = Math.max(0, this.speed - dt * 19);
    const previous = this.distance;
    this.distance = Math.min(length, this.distance + this.speed * dt);

    features.forEach((item, index) => {
      const position = item.fraction * length;
      if (this.passed.has(index) || previous >= position || this.distance < position) return;
      this.passed.add(index);
      if (Math.abs(item.lane - this.lateral) > 1.35) return;
      if (item.kind === "charge") {
        this.collected++;
        this.energy = Math.min(100, this.energy + 34);
        this.notify("氮气 +34");
      } else {
        this.impacts++;
        this.speed *= 0.44;
        this.notify("撞上路障 · 速度下降");
      }
    });

    while (this.checkpoint < gates.length && this.distance >= gates[this.checkpoint]) {
      this.checkpoint++;
      this.notify(`已通过检查点 ${this.checkpoint}/${gates.length}`);
    }
    if (this.distance >= length) {
      this.phase = "won";
      this.held.clear();
    }
  }

  private notify(message: string) {
    this.notice = message;
    this.noticeTime = 1.5;
  }
}
