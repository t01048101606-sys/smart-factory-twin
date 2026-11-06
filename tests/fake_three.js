export const registry = { meshes: [], lights: [], sprites: [] };
const vec = (x = 0, y = 0, z = 0) => ({ x, y, z, set(a, b, c) { this.x = a; this.y = b; this.z = c; return this; } });
class Obj { constructor() { this.position = vec(); this.scale = vec(1, 1, 1); this.rotation = vec(); this.visible = true; this.userData = {}; } }
const color = () => ({ setHex(v) { this.hex = v; }, set(v) { this.value = v; } });
const asNum = (o, k) => { for (const key of ['position', 'scale']) { const v = o[key]; if (v && ![v.x, v.y, v.z].every(Number.isFinite)) throw new Error(`NaN in ${k}.${key}`); } };
export const RepeatWrapping = 1000, SRGBColorSpace = 'srgb';
export class Scene extends Obj { constructor() { super(); this.children = []; this.background = null; } add(o) { this.children.push(o); return o; } }
export class Color { constructor(v) { this.hex = v; } setHex(v) { this.hex = v; } set(v) { this.value = v; } }
export class PerspectiveCamera extends Obj { constructor() { super(); this.aspect = 1; } updateProjectionMatrix() {} }
export class WebGLRenderer { constructor() { this.shadowMap = {}; this.domElement = { addEventListener() {} }; } setPixelRatio() {} setSize() {} render() { registry.renders = (registry.renders || 0) + 1; } }
export class AmbientLight extends Obj {}
export class DirectionalLight extends Obj { constructor() { super(); this.shadow = { mapSize: {}, camera: {} }; } }
export class PointLight extends Obj { constructor() { super(); this.intensity = 0; registry.lights.push(this); } }
export class BoxGeometry { constructor(...a) { this.type = 'Box'; this.args = a; } }
export class CylinderGeometry { constructor(...a) { this.type = 'Cylinder'; this.args = a; } }
export class SphereGeometry { constructor(...a) { this.type = 'Sphere'; this.args = a; } }
export class PlaneGeometry { constructor(...a) { this.type = 'Plane'; this.args = a; } }
export class MeshStandardMaterial { constructor(o = {}) { Object.assign(this, o); this.color = color(); if (o.color !== undefined) this.color.value = o.color; this.emissive = color(); if (o.emissive !== undefined) this.emissive.value = o.emissive; if (this.emissiveIntensity === undefined) this.emissiveIntensity = 0; } }
export class SpriteMaterial { constructor(o = {}) { Object.assign(this, o); } }
export class CanvasTexture { constructor(c) { this.canvas = c; this.repeat = { set() {} }; this.offset = { x: 0, y: 0 }; } }
export class Mesh extends Obj { constructor(g, m) { super(); this.geometry = g; this.material = m; registry.meshes.push(this); } }
export class Sprite extends Obj { constructor(m) { super(); this.material = m; registry.sprites.push(this); } }
export function check() { for (const m of [...registry.meshes, ...registry.lights, ...registry.sprites]) asNum(m, m.geometry ? m.geometry.type : 'obj'); }
