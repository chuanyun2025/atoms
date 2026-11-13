import * as THREE from "three";
import type { Race } from "./engine";
import { course, features, gates, length, roadHalfWidth, trackFrame } from "./track";

const material = (color: number) => new THREE.MeshStandardMaterial({ color, roughness: 0.76 });

function ribbon(from: number, to: number, y: number, colors: number[], dashed = false) {
  const positions: number[] = [], tint: number[] = [];
  const pieces = 192;
  for (let index = 0; index < pieces; index++) {
    if (dashed && index % 3 !== 0) continue;
    const a = index * length / pieces, b = (index + 1) * length / pieces;
    const corners = [trackFrame(a, from).point, trackFrame(a, to).point,
      trackFrame(b, from).point, trackFrame(b, to).point];
    const color = new THREE.Color(colors[index % colors.length]);
    for (const vertex of [0, 1, 2, 2, 1, 3]) {
      const point = corners[vertex];
      positions.push(point.x, y, point.z);
      tint.push(color.r, color.g, color.b);
    }
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  geometry.setAttribute("color", new THREE.Float32BufferAttribute(tint, 3));
  geometry.computeVertexNormals();
  return new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({vertexColors:true, side:THREE.DoubleSide}));
}

export class RaceView {
  private scene = new THREE.Scene();
  private camera = new THREE.PerspectiveCamera(65, 1, 0.12, 320);
  private renderer = new THREE.WebGLRenderer({ antialias:true, preserveDrawingBuffer:true });
  private car = new THREE.Group();
  private props: THREE.Mesh[] = [];
  private observer: ResizeObserver;
  private position = new THREE.Vector3();
  private previousDistance = 0;

  constructor(private surface: HTMLElement) {
    this.renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 1.25));
    this.renderer.domElement.dataset.raceViewport = "";
    surface.append(this.renderer.domElement);
    this.scene.background = new THREE.Color(course.scene.sky);
    this.scene.fog = new THREE.Fog(course.scene.haze, 68, 225);
    this.scene.add(new THREE.HemisphereLight(0xffe0c9, 0x46556d, 2));
    const light = new THREE.DirectionalLight(0xffc199, 2.1);
    light.position.set(-32, 45, 12);
    this.scene.add(light);
    const ground = new THREE.Mesh(new THREE.PlaneGeometry(850,850), material(course.scene.ground));
    ground.rotation.x = -Math.PI / 2;
    ground.position.y = -0.12;
    this.scene.add(ground);
    this.scene.add(ribbon(-roadHalfWidth, roadHalfWidth, 0.018, [0x2d3341,0x303645]));
    this.scene.add(ribbon(-0.07, 0.07, 0.034, [0xb5c0bc], true));
    for (const side of [-1,1]) {
      const edge = side * roadHalfWidth;
      this.scene.add(ribbon(Math.min(edge,edge+side*0.48), Math.max(edge,edge+side*0.48), 0.036,
        [course.scene.curb,0xf4e9dc]));
    }
    this.buildScenery();
    this.buildCar();
    this.observer = new ResizeObserver(() => this.resize());
    this.observer.observe(surface);
    this.resize();
  }

  private resize() {
    const width = Math.max(1, this.surface.clientWidth), height = Math.max(1, this.surface.clientHeight);
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(width,height,false);
  }

  private buildScenery() {
    const structures = new THREE.InstancedMesh(new THREE.BoxGeometry(1,1,1), material(0xa07c71), 92);
    const dummy = new THREE.Object3D();
    for(let i=0;i<structures.count;i++) {
      const side = i % 2 ? -1 : 1;
      const {point,heading} = trackFrame(i/structures.count*length, side * (13 + (i%7)*1.8));
      const height = 2.2 + (i%5)*1.3;
      dummy.position.copy(point).setY(height/2-0.1);
      dummy.scale.set(2.4+(i%3)*1.4,height,3.4);
      dummy.rotation.y = Math.atan2(heading.x,heading.z);
      dummy.updateMatrix();
      structures.setMatrixAt(i,dummy.matrix);
      structures.setColorAt(i,new THREE.Color([0xe7a578,0x8a96ae,0xb8877f,0x777a93][i%4]));
    }
    this.scene.add(structures);
    for (const distance of [0,...gates.slice(0,-1)]) {
      const {point,heading} = trackFrame(distance);
      const arch = new THREE.Group();
      const dark = material(0x343d4d);
      for(const x of [-7,7]) {
        const post=new THREE.Mesh(new THREE.BoxGeometry(0.52,5.6,0.62),dark);
        post.position.set(x,2.8,0); arch.add(post);
      }
      const beam=new THREE.Mesh(new THREE.BoxGeometry(14.4,0.63,0.7),dark);
      beam.position.y=5.45; arch.add(beam);
      const light=new THREE.Mesh(new THREE.BoxGeometry(10,0.1,0.08),new THREE.MeshBasicMaterial({color:0x52ebd9}));
      light.position.set(0,5.45,-0.39); arch.add(light);
      arch.position.copy(point);
      arch.rotation.y=Math.atan2(heading.x,heading.z);
      this.scene.add(arch);
    }
    for (const feature of features) {
      const {point,heading} = trackFrame(feature.fraction*length,feature.lane);
      const reward=feature.kind==="charge";
      const mesh=new THREE.Mesh(reward?new THREE.OctahedronGeometry(0.65):new THREE.BoxGeometry(2,0.92,0.65),
        reward?new THREE.MeshStandardMaterial({color:0x5cffdc,emissive:0x159f87,emissiveIntensity:1.2}):material(0xff7837));
      mesh.position.copy(point).setY(reward?1.15:0.45);
      mesh.rotation.y=Math.atan2(heading.x,heading.z);
      this.props.push(mesh);
      this.scene.add(mesh);
    }
  }

  private buildCar() {
    const part = (x:number,y:number,z:number,w:number,h:number,d:number,mat:THREE.Material) => {
      const mesh=new THREE.Mesh(new THREE.BoxGeometry(w,h,d),mat);
      mesh.position.set(x,y,z); this.car.add(mesh);
    };
    part(0,0.62,0,1.95,0.57,3.68,material(course.scene.car));
    part(0,1.03,-0.14,1.42,0.45,1.65,material(0x293a4d));
    part(0,0.44,-1.84,1.83,0.23,0.13,material(0x111520));
    part(0,1.04,-1.49,1.94,0.12,0.44,material(0x213542));
    for (const side of [-1,1]) {
      part(side*0.66,0.7,-1.86,0.38,0.12,0.08,new THREE.MeshBasicMaterial({color:0xff4039}));
      for (const z of [-1.16,1.16]) part(side*0.97,0.36,z,0.4,0.67,0.66,material(0x161b21));
    }
    this.scene.add(this.car);
  }

  draw(race: Race, dt: number) {
    const {point, heading} = trackFrame(race.distance,race.lateral);
    const ahead = trackFrame(race.distance+18,race.lateral*0.34).point;
    const desired = point.clone().addScaledVector(heading,-7.4-race.speed*0.05).setY(3.85+race.speed*0.027);
    if (race.distance < this.previousDistance || race.distance===0) this.position.copy(desired);
    else this.position.lerp(desired,Math.min(1,dt*11));
    this.previousDistance=race.distance;
    this.car.position.copy(point);
    this.car.rotation.y=Math.atan2(heading.x,heading.z)-race.steering*0.17;
    this.camera.position.copy(this.position);
    this.camera.lookAt(ahead.setY(1.16));
    this.camera.updateMatrixWorld();
    this.props.forEach((mesh,index)=>{
      mesh.visible=!race.passed.has(index);
      if (features[index].kind==="charge") mesh.rotation.y=race.seconds*2.2;
    });
    this.renderer.render(this.scene,this.camera);
    // Measure the rendered car relative to the same cross section of road.
    // Absolute screen X alone is ambiguous when the camera follows the car.
    const roadCenter=trackFrame(race.distance).point;
    return this.car.position.clone().project(this.camera).x-roadCenter.project(this.camera).x;
  }

  dispose() {
    this.observer.disconnect();
    this.scene.traverse(object=>{
      if (object instanceof THREE.Mesh) {
        object.geometry.dispose();
        if (object.material instanceof THREE.Material) object.material.dispose();
      }
    });
    this.renderer.dispose();
    this.renderer.domElement.remove();
  }
}
