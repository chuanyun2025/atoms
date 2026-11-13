import * as THREE from "three";
import { clipShotToCover } from "./shot-cover";
import {
  type Phase,
  type HudState,
  MAG_SIZE,
  ENEMY_COUNT,
  RELOAD_TIME,
  FIRE_INTERVAL,
  PLAYER_RADIUS,
  EYE_HEIGHT,
  ENEMY_HP,
  BULLET_DAMAGE,
  SPAWN,
  ENEMY_SPAWNS,
} from "./engine";

export type { Phase, HudState } from "./engine";

export function createInitialHud(): HudState {
  return {
    hp: 100,
    maxHp: 100,
    ammo: MAG_SIZE,
    magSize: MAG_SIZE,
    kills: 0,
    totalEnemies: ENEMY_COUNT,
    shots: 0,
    hits: 0,
    reloading: false,
    x: SPAWN.x,
    z: SPAWN.z,
    yaw: 0,
    pitch: -0.04,
    message: "",
    enemyShots: 0,
    enemyTracers: 0,
  };
}

interface Enemy {
  group: THREE.Group;
  body: THREE.Mesh;
  head: THREE.Mesh;
  hp: number;
  alive: boolean;
  speed: number;
  cooldown: number;
  home: THREE.Vector3;
  flash: number;
}

export class FpsGame {
  readonly container: HTMLElement;
  private renderer: THREE.WebGLRenderer;
  private scene: THREE.Scene;
  private camera: THREE.PerspectiveCamera;
  private raycaster = new THREE.Raycaster();
  private clock = new THREE.Clock();
  private frame = 0;
  private disposed = false;

  private obstacles: THREE.Box3[] = [];
  private enemies: Enemy[] = [];
  private hitables: THREE.Object3D[] = [];
  private enemyMeshes = new Map<THREE.Object3D, Enemy>();

  private keys = new Set<string>();
  private yaw = 0;
  private pitch = -0.04;
  private pos = new THREE.Vector3(SPAWN.x, 0, SPAWN.z);
  private velY = 0;
  private onGround = true;

  private hp = 100;
  private ammo = MAG_SIZE;
  private reloadTimer = 0;
  private fireTimer = 0;
  private shots = 0;
  private hits = 0;
  private kills = 0;
  private message = "";
  private messageTime = 0;
  private recoil = 0;
  private muzzle: THREE.Mesh;
  private gunGroup: THREE.Group;
  private gunRecoil = 0;
  private enemyShots = 0;
  private enemyTracers: { mesh: THREE.Mesh<THREE.BoxGeometry, THREE.MeshBasicMaterial>; time: number }[] = [];

  phase: Phase = "ready";
  private touchLook: { id: number; x: number; y: number } | null = null;
  private hadPointerLock = false;
  private fireRaf = 0;
  private damageDecals: THREE.Mesh[] = [];

  actions = 0;
  onChange: (s: HudState) => void = () => {};

  constructor(container: HTMLElement) {
    this.container = container;
    this.renderer = new THREE.WebGLRenderer({
      antialias: true,
      preserveDrawingBuffer: true,
    });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.25));
    this.renderer.domElement.setAttribute("data-fps-viewport", "");
    this.renderer.domElement.style.display = "block";
    this.renderer.domElement.style.width = "100%";
    this.renderer.domElement.style.height = "100%";
    this.renderer.domElement.style.touchAction = "none";
    container.appendChild(this.renderer.domElement);

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x1a2028);
    this.scene.fog = new THREE.Fog(0x1a2028, 16, 46);

    this.camera = new THREE.PerspectiveCamera(72, 1, 0.05, 120);
    this.camera.rotation.order = "YXZ";
    this.scene.add(this.camera);

    this.buildLights();
    this.buildArena();
    this.gunGroup = this.buildGun();
    this.muzzle = this.buildMuzzle();
    this.spawnEnemies();
    this.resize();

    window.addEventListener("resize", this.resize);
    const el = this.renderer.domElement;
    el.tabIndex = 0;
    el.addEventListener("pointerdown", this.onPointerDown);
    window.addEventListener("pointermove", this.onPointerMove);
    el.addEventListener("lostpointercapture", this.onTouchEnd);
    document.addEventListener("pointerlockchange", this.onPointerLockChange);
    window.addEventListener("keydown", this.onKeyDown);
    window.addEventListener("keyup", this.onKeyUp);
    window.addEventListener("blur", this.onBlur);
    document.addEventListener("visibilitychange", this.onVisibility);

    this.applyCamera();
    this.emit();
    this.clock.start();
    this.frame = requestAnimationFrame(this.loop);
  }

  private resize = () => {
    const w = this.container.clientWidth || 640;
    const h = this.container.clientHeight || 420;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  };

  private buildLights() {
    this.scene.add(new THREE.HemisphereLight(0x9fb4c9, 0x232a30, 0.9));
    const dir = new THREE.DirectionalLight(0xdfe7f0, 0.75);
    dir.position.set(8, 16, 6);
    this.scene.add(dir);
    const lamps = [
      [-8, 7, -8],
      [8, 7, -8],
      [0, 7, 4],
      [-8, 7, 8],
    ];
    for (const [x, y, z] of lamps) {
      const l = new THREE.PointLight(0xffe0a3, 0.7, 22);
      l.position.set(x, y, z);
      this.scene.add(l);
      const holder = new THREE.Mesh(
        new THREE.BoxGeometry(1.2, 0.12, 0.5),
        new THREE.MeshBasicMaterial({ color: 0xffe9b8 })
      );
      holder.position.set(x, y + 0.6, z);
      this.scene.add(holder);
    }
  }

  private addBox(
    x: number,
    y: number,
    z: number,
    w: number,
    h: number,
    d: number,
    color: number,
    collide = true
  ) {
    const geo = new THREE.BoxGeometry(w, h, d);
    const mat = new THREE.MeshStandardMaterial({ color, roughness: 0.85, metalness: 0.15 });
    const mesh = new THREE.Mesh(geo, mat);
    mesh.position.set(x, y, z);
    this.scene.add(mesh);
    if (collide) {
      const box = new THREE.Box3().setFromObject(mesh);
      this.obstacles.push(box);
    }
    return mesh;
  }

  private buildArena() {
    const floorMat = new THREE.MeshStandardMaterial({ color: 0x4b5058, roughness: 1 });
    const floor = new THREE.Mesh(new THREE.PlaneGeometry(40, 40), floorMat);
    floor.rotation.x = -Math.PI / 2;
    this.scene.add(floor);

    const grid = new THREE.GridHelper(40, 40, 0x30363d, 0x2a3036);
    grid.position.y = 0.01;
    (grid.material as THREE.Material).transparent = true;
    (grid.material as THREE.Material).opacity = 0.5;
    this.scene.add(grid);

    const H = 5;
    this.addBox(0, H / 2, -18, 40, H, 0.6, 0x39414a);
    this.addBox(0, H / 2, 18, 40, H, 0.6, 0x39414a);
    this.addBox(-18, H / 2, 0, 0.6, H, 40, 0x39414a);
    this.addBox(18, H / 2, 0, 0.6, H, 40, 0x39414a);

    this.addBox(-6, 1.2, 0, 2.4, 2.4, 2.4, 0x5b6b3d);
    this.addBox(-4.5, 1.2, -2, 2.4, 2.4, 2.4, 0x4d5c36);
    this.addBox(6, 1.3, -2, 2.6, 2.6, 2.6, 0x3f566d);
    this.addBox(4.5, 1.3, 2, 2.6, 2.6, 2.6, 0x3a4f63);
    this.addBox(0, 1.6, -6, 4.5, 3.2, 1.2, 0x4a525c);
    this.addBox(-9, 1.0, -10, 3, 2, 3, 0x5b6b3d);
    this.addBox(9, 1.0, -10, 3, 2, 3, 0x3f566d);
    this.addBox(-10, 1.4, 8, 2.8, 2.8, 2.8, 0x4a525c);
    this.addBox(10, 1.4, 8, 2.8, 2.8, 2.8, 0x5b6b3d);
    this.addBox(0, 0.9, -14, 6, 1.8, 1.2, 0x414b55);
  }

  private buildGun() {
    const g = new THREE.Group();
    const mat = new THREE.MeshStandardMaterial({ color: 0x23272c, roughness: 0.55 });
    const body = new THREE.Mesh(new THREE.BoxGeometry(0.12, 0.14, 0.5), mat);
    body.position.set(0, 0, -0.1);
    g.add(body);
    const barrel = new THREE.Mesh(new THREE.CylinderGeometry(0.028, 0.028, 0.4, 8), mat);
    barrel.rotation.x = Math.PI / 2;
    barrel.position.set(0, 0.02, -0.5);
    g.add(barrel);
    const grip = new THREE.Mesh(new THREE.BoxGeometry(0.08, 0.2, 0.1), mat);
    grip.position.set(0, -0.14, 0.08);
    g.add(grip);
    const mag = new THREE.Mesh(new THREE.BoxGeometry(0.07, 0.18, 0.1), mat);
    mag.position.set(0, -0.13, -0.12);
    g.add(mag);
    const sight = new THREE.Mesh(new THREE.BoxGeometry(0.05, 0.06, 0.05), mat);
    sight.position.set(0, 0.1, -0.15);
    g.add(sight);
    g.position.set(0.22, -0.2, -0.45);
    this.camera.add(g);
    return g;
  }

  private buildMuzzle() {
    const m = new THREE.Mesh(
      new THREE.SphereGeometry(0.07, 8, 8),
      new THREE.MeshBasicMaterial({ color: 0xffd166, transparent: true, opacity: 0.95 })
    );
    m.position.set(0, 0.02, -0.7);
    m.visible = false;
    this.gunGroup.add(m);
    return m;
  }

  private spawnEnemies() {
    for (const [x, z] of ENEMY_SPAWNS) {
      const group = new THREE.Group();
      const bodyMat = new THREE.MeshStandardMaterial({ color: 0x6b1d22, roughness: 0.7 });
      const body = new THREE.Mesh(new THREE.BoxGeometry(0.7, 1.25, 0.42), bodyMat);
      body.position.y = 0.85;
      group.add(body);
      const head = new THREE.Mesh(
        new THREE.BoxGeometry(0.42, 0.42, 0.42),
        new THREE.MeshStandardMaterial({ color: 0x2b2b2f, roughness: 0.6 })
      );
      head.position.y = 1.68;
      group.add(head);
      const legs = new THREE.Mesh(
        new THREE.BoxGeometry(0.56, 0.55, 0.36),
        new THREE.MeshStandardMaterial({ color: 0x3a3a40 })
      );
      legs.position.y = 0.3;
      group.add(legs);
      const eye = new THREE.Mesh(
        new THREE.BoxGeometry(0.26, 0.08, 0.02),
        new THREE.MeshBasicMaterial({ color: 0xff3b3b })
      );
      eye.position.set(0, 0.74, 0.22);
      body.add(eye);
      group.position.set(x, 0, z);
      this.scene.add(group);
      const e: Enemy = {
        group,
        body,
        head,
        hp: ENEMY_HP,
        alive: true,
        speed: 1.5 + Math.random() * 0.5,
        cooldown: 1.2 + Math.random(),
        home: new THREE.Vector3(x, 0, z),
        flash: 0,
      };
      this.enemies.push(e);
      this.enemyMeshes.set(body, e);
      this.enemyMeshes.set(head, e);
      this.hitables.push(body, head);
    }
  }

  private onPointerDown = (e: PointerEvent) => {
    if (this.phase !== "playing") return;
    if (e.pointerType === "mouse") {
      if (e.button === 0) this.fire();
      return;
    }
    if (this.touchLook) return;
    this.touchLook = { id: e.pointerId, x: e.clientX, y: e.clientY };
    this.renderer.domElement.setPointerCapture(e.pointerId);
  };

  private onPointerMove = (e: PointerEvent) => {
    if (this.phase !== "playing") return;
    const canvas = this.renderer.domElement;
    if (e.pointerType === "mouse") {
      if (document.pointerLockElement === canvas || e.target === canvas) {
        this.turn(e.movementX * 0.0032, e.movementY * 0.0026);
      }
      return;
    }
    const touch = this.touchLook;
    if (touch?.id !== e.pointerId) return;
    this.turn((e.clientX - touch.x) * 0.0032, (e.clientY - touch.y) * 0.0026);
    touch.x = e.clientX;
    touch.y = e.clientY;
  };

  private onTouchEnd = (e: PointerEvent) => {
    if (this.touchLook?.id === e.pointerId) this.touchLook = null;
  };

  private onPointerLockChange = () => {
    const locked = document.pointerLockElement === this.renderer.domElement;
    if (this.hadPointerLock && !locked) this.gamePause();
    this.hadPointerLock = locked;
    if (locked && this.phase !== "playing") this.releaseInput();
  };

  private captureMouse() {
    const canvas = this.renderer.domElement;
    canvas.focus({ preventScroll: true });
    if (!matchMedia("(any-pointer: fine)").matches) return;
    try {
      const pending = canvas.requestPointerLock?.();
      pending?.catch(() => {});
    } catch {
      // A focused canvas still supports mouse movement when locking is denied.
    }
  }

  private releaseInput() {
    this.keys.clear();
    const touch = this.touchLook;
    const canvas = this.renderer.domElement;
    this.touchLook = null;
    if (touch && canvas.hasPointerCapture(touch.id)) canvas.releasePointerCapture(touch.id);
    if (document.pointerLockElement === canvas) document.exitPointerLock();
  }

  private onKeyDown = (e: KeyboardEvent) => {
    if (this.phase !== "playing") return;
    if (e.code === "Escape") {
      this.gamePause();
      return;
    }
    if (e.code === "KeyR") {
      this.reload();
      return;
    }
    if (["KeyW", "KeyA", "KeyS", "KeyD", "Space", "ShiftLeft", "ShiftRight"].includes(e.code)) {
      this.keys.add(e.code);
      if (e.code === "Space") e.preventDefault();
    }
  };

  private onKeyUp = (e: KeyboardEvent) => {
    this.keys.delete(e.code);
  };

  private onBlur = () => {
    this.gamePause();
  };

  private onVisibility = () => {
    if (document.hidden) this.onBlur();
  };

  private applyCamera() {
    const bob = this.phase === "playing" ? Math.sin(performance.now() * 0.004) * 0.012 : 0;
    this.camera.position.set(this.pos.x, EYE_HEIGHT + this.jumpY + bob, this.pos.z);
    this.camera.rotation.y = this.yaw;
    this.camera.rotation.x = this.pitch + this.recoil;
    this.camera.updateMatrixWorld();
  }

  private collides(x: number, z: number) {
    for (const b of this.obstacles) {
      if (
        x + PLAYER_RADIUS > b.min.x &&
        x - PLAYER_RADIUS < b.max.x &&
        z + PLAYER_RADIUS > b.min.z &&
        z - PLAYER_RADIUS < b.max.z
      ) {
        return true;
      }
    }
    return false;
  }

  private fire() {
    if (this.phase !== "playing") return;
    if (this.reloadTimer > 0) return;
    if (this.fireTimer > 0) return;
    if (this.ammo <= 0) {
      this.say("弹匣空了！按 R 换弹");
      this.emit();
      return;
    }
    this.ammo -= 1;
    this.shots += 1;
    this.actions += 1;
    this.fireTimer = FIRE_INTERVAL;
    this.recoil = Math.min(0.09, this.recoil + 0.03);
    this.gunRecoil = 0.16;
    this.muzzle.visible = true;
    this.muzzle.scale.setScalar(0.8 + Math.random() * 0.9);
    cancelAnimationFrame(this.fireRaf);
    this.fireRaf = requestAnimationFrame(() => {
      this.muzzle.visible = false;
    });

    this.raycaster.setFromCamera(new THREE.Vector2(0, 0), this.camera);
    const ray = this.raycaster.ray;
    const cover = clipShotToCover(ray.origin, ray.at(this.camera.far, new THREE.Vector3()), this.obstacles);
    const hit = this.raycaster.intersectObjects(this.hitables, false)[0];
    const enemy = hit && this.enemyMeshes.get(hit.object);
    if (hit && enemy?.alive && hit.distance < cover.distance) {
      this.hits += 1;
      this.damageEnemy(enemy, BULLET_DAMAGE, hit.point);
    } else if (cover.blocked) {
      this.spawnImpact(cover.point);
    }
    this.emit();
  }

  private spawnImpact(point: THREE.Vector3) {
    const m = new THREE.Mesh(
      new THREE.SphereGeometry(0.06, 6, 6),
      new THREE.MeshBasicMaterial({ color: 0xffcf70 })
    );
    m.position.copy(point);
    this.scene.add(m);
    this.damageDecals.push(m);
    setTimeout(() => {
      if (this.disposed) return;
      this.scene.remove(m);
      m.geometry.dispose();
      (m.material as THREE.Material).dispose();
      this.damageDecals = this.damageDecals.filter((d) => d !== m);
    }, 300);
  }

  private damageEnemy(enemy: Enemy, dmg: number, point: THREE.Vector3) {
    enemy.hp -= dmg;
    enemy.flash = 0.18;
    (enemy.body.material as THREE.MeshStandardMaterial).emissive.setHex(0xffffff);
    this.spawnImpact(point);
    if (enemy.hp <= 0) {
      enemy.alive = false;
      enemy.group.visible = false;
      this.kills += 1;
      this.say(`击杀 ${this.kills}/${ENEMY_COUNT}`);
      this.hitables = this.hitables.filter((h) => h !== enemy.body && h !== enemy.head);
      if (this.kills >= ENEMY_COUNT) {
        this.phase = "won";
        this.releaseInput();
      }
    }
    this.emit();
  }

  private reload() {
    if (this.phase !== "playing") return;
    if (this.reloadTimer > 0) return;
    if (this.ammo === MAG_SIZE) return;
    this.reloadTimer = RELOAD_TIME;
    this.say("换弹中…");
    this.emit();
  }

  private say(msg: string) {
    this.message = msg;
    this.messageTime = 2.2;
  }

  private update(dt: number) {
    if (this.phase !== "playing") return;
    const d = Math.min(dt, 0.05);
    this.updateEnemyTracers(d);

    if (this.reloadTimer > 0) {
      this.reloadTimer -= d;
      if (this.reloadTimer <= 0) {
        this.reloadTimer = 0;
        this.ammo = MAG_SIZE;
        this.say("装填完成");
        this.emit();
      }
    }
    if (this.fireTimer > 0) this.fireTimer -= d;
    this.recoil = Math.max(0, this.recoil - d * 0.4);
    this.gunRecoil = Math.max(0, this.gunRecoil - d * 1.2);
    if (this.messageTime > 0) this.messageTime -= d;

    const speed =
      (this.keys.has("ShiftLeft") || this.keys.has("ShiftRight") ? 6.2 : 3.8) * d;
    let fx = 0;
    let fz = 0;
    if (this.keys.has("KeyW")) fz -= 1;
    if (this.keys.has("KeyS")) fz += 1;
    if (this.keys.has("KeyA")) fx -= 1;
    if (this.keys.has("KeyD")) fx += 1;
    if (fx !== 0 || fz !== 0) {
      const len = Math.hypot(fx, fz);
      fx /= len;
      fz /= len;
      const cos = Math.cos(this.yaw);
      const sin = Math.sin(this.yaw);
      const dx = (fx * cos + fz * sin) * speed;
      const dz = (fz * cos - fx * sin) * speed;
      const oldX = this.pos.x;
      const oldZ = this.pos.z;
      const nx = oldX + dx;
      const nz = oldZ + dz;
      if (!this.collides(nx, this.pos.z)) this.pos.x = nx;
      if (!this.collides(this.pos.x, nz)) this.pos.z = nz;
      // 位置变化视为一次已接受动作（由引擎判定，非渲染伪造）
      this.moved = this.pos.x !== oldX || this.pos.z !== oldZ;
    }

    if (this.keys.has("Space") && this.onGround) {
      this.velY = 4.2;
      this.onGround = false;
    }
    if (!this.onGround) {
      this.velY -= 9.8 * d;
      this.jumpY = Math.max(0, this.jumpY + this.velY * d);
      if (this.jumpY <= 0) {
        this.jumpY = 0;
        this.velY = 0;
        this.onGround = true;
      }
    }

    for (const e of this.enemies) {
      if (!e.alive) continue;
      if (e.flash > 0) {
        e.flash -= d;
        if (e.flash <= 0) {
          (e.body.material as THREE.MeshStandardMaterial).emissive.setHex(0x000000);
        }
      }
      const toPlayer = new THREE.Vector3().subVectors(this.pos, e.group.position);
      const dist = toPlayer.length();
      toPlayer.y = 0;
      toPlayer.normalize();
      if (dist > 9) {
        const moveV = toPlayer.multiplyScalar(e.speed * d);
        const nx = e.group.position.x + moveV.x;
        const nz = e.group.position.z + moveV.z;
        if (!this.collides(nx, nz)) {
          e.group.position.x = nx;
          e.group.position.z = nz;
        }
      }
      e.group.lookAt(this.pos.x, e.group.position.y, this.pos.z);
      e.group.rotation.x = 0;
      e.group.rotation.z = 0;

      e.cooldown -= d;
      if (e.cooldown <= 0 && dist < 14) {
        e.cooldown = 1.4 + Math.random() * 0.8;
        this.enemyFire(e);
      }
    }

    this.applyCamera();
    this.gunGroup.position.set(
      0.22,
      -0.2 - this.gunRecoil * 0.25,
      -0.45 + this.gunRecoil * 0.3
    );
  }

  private moved = false;
  private jumpY = 0;

  private enemyFire(enemy: Enemy) {
    const origin = enemy.group.position.clone().add(new THREE.Vector3(0, 1.2, 0));
    const target = new THREE.Vector3(this.pos.x, 1.3 + this.jumpY, this.pos.z);
    const shot = clipShotToCover(origin, target, this.obstacles);
    if (shot.distance > 0.02) {
      const tracer = new THREE.Mesh(
        new THREE.BoxGeometry(0.028, 0.028, shot.distance),
        new THREE.MeshBasicMaterial({ color: 0xff824e, transparent: true, depthTest: true, depthWrite: false }),
      );
      tracer.position.copy(origin).lerp(shot.point, 0.5);
      tracer.lookAt(shot.point);
      this.scene.add(tracer);
      this.enemyTracers.push({ mesh: tracer, time: 0.30 });
    }
    this.enemyShots++;
    if (shot.blocked) {
      this.spawnImpact(shot.point);
      this.emit();
    } else {
      this.hurt(8 + Math.round(Math.random() * 6));
    }
  }

  private updateEnemyTracers(dt: number) {
    for (const tracer of this.enemyTracers) {
      tracer.time -= dt;
      tracer.mesh.material.opacity = Math.min(1, tracer.time * 6);
      if (tracer.time <= 0) this.disposeTracer(tracer.mesh);
    }
    const active = this.enemyTracers.filter(tracer => tracer.time > 0);
    if (active.length !== this.enemyTracers.length) {
      this.enemyTracers = active;
      this.emit();
    }
  }

  private disposeTracer(mesh: THREE.Mesh<THREE.BoxGeometry, THREE.MeshBasicMaterial>) {
    this.scene.remove(mesh);
    mesh.geometry.dispose();
    mesh.material.dispose();
  }

  private hurt(amount: number) {
    if (this.phase !== "playing") return;
    this.hp = Math.max(0, this.hp - amount);
    this.say(`-${amount} 生命`);
    if (this.hp <= 0) {
      this.phase = "lost";
      this.releaseInput();
    }
    this.emit();
  }

  gameStart() {
    this.reset();
    this.phase = "playing";
    this.clock.getDelta();
    this.captureMouse();
    this.emit();
  }

  gamePause() {
    if (this.phase === "playing") {
      this.phase = "paused";
      this.releaseInput();
      this.emit();
    }
  }

  gameResume() {
    if (this.phase === "paused") {
      this.phase = "playing";
      this.clock.getDelta();
      this.captureMouse();
      this.emit();
    }
  }

  gameRestart() {
    this.reset();
    this.phase = "ready";
    this.emit();
  }

  /** 触屏/键盘按钮注入移动输入，持续到释放。 */
  setKey(code: string, down: boolean) {
    if (this.phase !== "playing") return;
    if (down) this.keys.add(code);
    else this.keys.delete(code);
  }

  /** 触屏转向按钮。 */
  turn(dx: number, dy: number) {
    if (this.phase !== "playing") return;
    this.yaw -= dx;
    this.pitch = Math.max(-1.2, Math.min(1.2, this.pitch - dy));
    this.applyCamera();
    this.emit();
  }

  private reset() {
    this.releaseInput();
    for (const { mesh } of this.enemyTracers) this.disposeTracer(mesh);
    this.enemyTracers = [];
    this.enemyShots = 0;
    this.pos.set(SPAWN.x, 0, SPAWN.z);
    this.jumpY = 0;
    this.yaw = 0;
    this.pitch = -0.04;
    this.velY = 0;
    this.onGround = true;
    this.hp = 100;
    this.ammo = MAG_SIZE;
    this.reloadTimer = 0;
    this.fireTimer = 0;
    this.shots = 0;
    this.hits = 0;
    this.kills = 0;
    this.actions = 0;
    this.message = "";
    this.messageTime = 0;
    this.recoil = 0;
    this.gunRecoil = 0;
    this.moved = false;
    this.hitables = [];
    this.enemyMeshes.clear();
    for (const e of this.enemies) {
      e.alive = true;
      e.hp = ENEMY_HP;
      e.group.visible = true;
      e.group.position.copy(e.home);
      e.cooldown = 1.2 + Math.random();
      e.flash = 0;
      (e.body.material as THREE.MeshStandardMaterial).emissive.setHex(0x000000);
      this.hitables.push(e.body, e.head);
      this.enemyMeshes.set(e.body, e);
      this.enemyMeshes.set(e.head, e);
    }
    this.applyCamera();
  }

  private emit() {
    this.onChange({
      hp: Math.round(this.hp),
      maxHp: 100,
      ammo: this.ammo,
      magSize: MAG_SIZE,
      kills: this.kills,
      totalEnemies: ENEMY_COUNT,
      shots: this.shots,
      hits: this.hits,
      reloading: this.reloadTimer > 0,
      x: this.pos.x,
      z: this.pos.z,
      yaw: this.yaw,
      pitch: this.pitch,
      message: this.messageTime > 0 ? this.message : "",
      enemyShots: this.enemyShots,
      enemyTracers: this.enemyTracers.length,
    });
  }

  publicFire() {
    this.fire();
  }

  publicReload() {
    this.reload();
  }

  private loop = () => {
    if (this.disposed) return;
    const dt = this.clock.getDelta();
    this.update(dt);
    // 移动已在 update 内发生，这里按帧把已接受移动计为动作
    if (this.phase === "playing" && this.moved) {
      this.actions += 1;
      this.moved = false;
      this.emit();
    }
    this.renderer.render(this.scene, this.camera);
    this.frame = requestAnimationFrame(this.loop);
  };

  dispose() {
    this.disposed = true;
    cancelAnimationFrame(this.frame);
    cancelAnimationFrame(this.fireRaf);
    window.removeEventListener("resize", this.resize);
    const el = this.renderer.domElement;
    document.removeEventListener("pointerlockchange", this.onPointerLockChange);
    this.releaseInput();
    el.removeEventListener("pointerdown", this.onPointerDown);
    el.removeEventListener("lostpointercapture", this.onTouchEnd);
    window.removeEventListener("pointermove", this.onPointerMove);
    window.removeEventListener("keydown", this.onKeyDown);
    window.removeEventListener("keyup", this.onKeyUp);
    window.removeEventListener("blur", this.onBlur);
    document.removeEventListener("visibilitychange", this.onVisibility);
    for (const d of this.damageDecals) {
      this.scene.remove(d);
      d.geometry.dispose();
      (d.material as THREE.Material).dispose();
    }
    this.damageDecals = [];
    this.scene.traverse((obj) => {
      const mesh = obj as THREE.Mesh;
      if (mesh.geometry) mesh.geometry.dispose();
      const mat = mesh.material as THREE.Material | THREE.Material[];
      if (Array.isArray(mat)) mat.forEach((m) => m.dispose());
      else if (mat) mat.dispose();
    });
    this.renderer.dispose();
    if (el.parentElement) el.parentElement.removeChild(el);
  }
}
