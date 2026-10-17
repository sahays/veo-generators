import type {
  StoryGraphData,
  StoryGraphEntity as StoryEntityNode,
  StoryGraphAppearance as EntityAppearanceNode,
  StoryGraphScene as StorySceneNode,
  StoryGraphEvent as StoryEventNode,
  StoryGraphShot as StoryShotNode,
  StoryGraphGenerationRun as GenerationRunNode,
  StoryGraphAttributeValue,
} from '@/types/project'

export type GraphNodeKind =
  | 'style'
  | 'character'
  | 'location'
  | 'object'
  | 'scene'
  | 'event'
  | 'appearance'
  | 'shot'

export interface GraphNode3D {
  id: string
  label: string
  sublabel: string
  kind: GraphNodeKind
  status?: string
  imageUrl?: string
  videoUrl?: string
  details?: Record<string, string>
  appearanceId?: string
  x: number
  y: number
  z: number
  vx: number
  vy: number
  vz: number
  radius: number
  color: string
  glowColor: string
}

export interface GraphEdge3D {
  id: string
  source: string
  target: string
  label: string
  color: string
}

export const KIND_META: Record<
  GraphNodeKind,
  { label: string; color: string; glow: string; baseRadius: number }
> = {
  style: { label: 'Style Guide', color: '#f59e0b', glow: 'rgba(245, 158, 11, 0.55)', baseRadius: 24 },
  character: { label: 'Character', color: '#10b981', glow: 'rgba(16, 185, 129, 0.5)', baseRadius: 19 },
  location: { label: 'Location', color: '#8b5cf6', glow: 'rgba(139, 92, 246, 0.5)', baseRadius: 19 },
  object: { label: 'Prop / Object', color: '#ec4899', glow: 'rgba(236, 72, 153, 0.5)', baseRadius: 16 },
  scene: { label: 'Scene', color: '#3b82f6', glow: 'rgba(59, 130, 246, 0.5)', baseRadius: 18 },
  event: { label: 'Story Event', color: '#06b6d4', glow: 'rgba(6, 182, 212, 0.45)', baseRadius: 13 },
  appearance: { label: 'Design Sheet', color: '#eab308', glow: 'rgba(234, 179, 8, 0.45)', baseRadius: 15 },
  shot: { label: 'Rendered Shot', color: '#f43f5e', glow: 'rgba(244, 63, 94, 0.5)', baseRadius: 17 },
}

function formatAttributes(
  attributes?: Record<string, StoryGraphAttributeValue | string>,
): Record<string, string> {
  const attrs: Record<string, string> = {}
  Object.entries(attributes || {}).forEach(([k, v]) => {
    attrs[k] = typeof v === 'object' && v && 'value' in v && v.value !== undefined ? String(v.value) : String(v)
  })
  return attrs
}

function buildImageLookups(appearances: EntityAppearanceNode[]) {
  const entityPrimaryImg: Record<string, string> = {}
  const appearanceImg: Record<string, string> = {}
  for (const app of appearances) {
    const lastAsset = app.assets?.[app.assets.length - 1]
    if (lastAsset?.signed_url) {
      appearanceImg[app.id] = lastAsset.signed_url
      if (!entityPrimaryImg[app.entity_id] || app.state_label === 'default') {
        entityPrimaryImg[app.entity_id] = lastAsset.signed_url
      }
    }
  }
  return { entityPrimaryImg, appearanceImg }
}

function addEntityRingNodes(
  entities: StoryEntityNode[], kind: 'character' | 'location' | 'object', styleId: string,
  edgeColor: string, entityPrimaryImg: Record<string, string>, nodes: GraphNode3D[], edges: GraphEdge3D[],
) {
  const r = kind === 'character' ? 150 : kind === 'location' ? 185 : 140
  const angleOffset = kind === 'location' ? 0.4 : kind === 'object' ? 1.1 : 0
  entities.forEach((ent, idx) => {
    const angle = (idx / Math.max(1, entities.length)) * Math.PI * 2 + angleOffset
    const y = kind === 'character' ? -70 + (idx % 2) * 30 : kind === 'location' ? 20 : -115
    nodes.push({
      id: ent.id, label: ent.canonical_name,
      sublabel: kind === 'character' ? 'Character' : kind === 'location' ? 'Location' : 'Hero Prop',
      kind, status: ent.status, imageUrl: entityPrimaryImg[ent.id],
      details: kind === 'object' ? { Type: 'Hero Prop / Object', ID: ent.id } : formatAttributes(ent.attributes),
      x: Math.cos(angle) * r, y, z: Math.sin(angle) * r, vx: 0, vy: 0, vz: 0,
      radius: KIND_META[kind].baseRadius, color: KIND_META[kind].color, glowColor: KIND_META[kind].glow,
    })
    edges.push({ id: `e_${styleId}_${ent.id}`, source: styleId, target: ent.id, label: 'styles', color: edgeColor })
  })
}

function addAppearanceNodes(appearances: EntityAppearanceNode[], appearanceImg: Record<string, string>, nodes: GraphNode3D[], edges: GraphEdge3D[]) {
  appearances.forEach((app, idx) => {
    const angle = (idx / Math.max(1, appearances.length)) * Math.PI * 2 + 0.25
    nodes.push({
      id: app.id, label: `${app.entity_id.replace(/^(char_|loc_|obj_)/, '')} (${app.state_label})`,
      sublabel: `v${app.version} · ${app.status}`, kind: 'appearance', status: app.status,
      imageUrl: appearanceImg[app.id], appearanceId: app.id,
      details: { Entity: app.entity_id, State: app.state_label, Description: app.visual_description || '', Wardrobe: app.wardrobe || 'N/A', Status: app.status },
      x: Math.cos(angle) * 235, y: -45 + (idx % 3) * 35, z: Math.sin(angle) * 235, vx: 0, vy: 0, vz: 0,
      radius: KIND_META.appearance.baseRadius, color: KIND_META.appearance.color, glowColor: KIND_META.appearance.glow,
    })
    edges.push({ id: `e_${app.entity_id}_${app.id}`, source: app.entity_id, target: app.id, label: app.state_label, color: 'rgba(234, 179, 8, 0.45)' })
  })
}

function addSceneAndEventNodes(scenes: StorySceneNode[], events: StoryEventNode[], nodes: GraphNode3D[], edges: GraphEdge3D[]) {
  scenes.forEach((sc, idx) => {
    const angle = (idx / Math.max(1, scenes.length)) * Math.PI * 2
    nodes.push({
      id: sc.id, label: `Scene ${sc.index || idx + 1}`, sublabel: sc.heading || sc.summary?.slice(0, 32) || sc.id,
      kind: 'scene', status: sc.status,
      details: { Heading: sc.heading || '', Time: sc.time_of_day || '', Summary: sc.summary || '', Location: sc.location_id || '' },
      x: Math.cos(angle) * 170, y: 95, z: Math.sin(angle) * 170, vx: 0, vy: 0, vz: 0,
      radius: KIND_META.scene.baseRadius, color: KIND_META.scene.color, glowColor: KIND_META.scene.glow,
    })
    if (sc.location_id) edges.push({ id: `e_${sc.id}_${sc.location_id}`, source: sc.id, target: sc.location_id, label: 'set_at', color: 'rgba(59, 130, 246, 0.4)' })
  })
  events.forEach((ev, idx) => {
    const angle = (idx / Math.max(1, events.length)) * Math.PI * 2 + 0.3
    nodes.push({
      id: ev.id, label: `Event #${ev.story_order}`, sublabel: ev.summary?.slice(0, 36) || ev.id,
      kind: 'event', status: ev.status,
      details: { Order: String(ev.story_order), Scene: ev.scene_id, Summary: ev.summary || '', Participants: (ev.participant_ids || []).join(', ') },
      x: Math.cos(angle) * 215, y: 125, z: Math.sin(angle) * 215, vx: 0, vy: 0, vz: 0,
      radius: KIND_META.event.baseRadius, color: KIND_META.event.color, glowColor: KIND_META.event.glow,
    })
    if (ev.scene_id) edges.push({ id: `e_${ev.scene_id}_${ev.id}`, source: ev.scene_id, target: ev.id, label: 'event', color: 'rgba(6, 182, 212, 0.4)' })
  })
}

function addAppearanceAndSceneNodes(
  appearances: EntityAppearanceNode[], scenes: StorySceneNode[], events: StoryEventNode[],
  appearanceImg: Record<string, string>, nodes: GraphNode3D[], edges: GraphEdge3D[],
) {
  addAppearanceNodes(appearances, appearanceImg, nodes, edges)
  addSceneAndEventNodes(scenes, events, nodes, edges)
}

function addShotEdges(sh: StoryShotNode, edges: GraphEdge3D[]) {
  if (sh.scene_id) edges.push({ id: `e_${sh.scene_id}_${sh.id}`, source: sh.scene_id, target: sh.id, label: 'shot', color: 'rgba(244, 63, 94, 0.45)' })
  for (const c of sh.cast || []) {
    const src = c.appearance_id || c.entity_id
    if (src) {
      edges.push({
        id: `e_${src}_${sh.id}`, source: src, target: sh.id,
        label: c.appearance_id ? 'cast_ref' : 'cast',
        color: c.appearance_id ? 'rgba(234, 179, 8, 0.3)' : 'rgba(16, 185, 129, 0.3)',
      })
    }
  }
}

function addShotNodes(shots: StoryShotNode[], runs: GenerationRunNode[], nodes: GraphNode3D[], edges: GraphEdge3D[]) {
  const latestRunByShot: Record<string, GenerationRunNode> = {}
  for (const r of runs) {
    if (!latestRunByShot[r.shot_id] || r.attempt >= latestRunByShot[r.shot_id].attempt) latestRunByShot[r.shot_id] = r
  }
  shots.forEach((sh, idx) => {
    const angle = (idx / Math.max(1, shots.length)) * Math.PI * 2
    const latestRun = latestRunByShot[sh.id]
    const isApproved = latestRun?.status === 'approved'
    nodes.push({
      id: sh.id, label: sh.id.replace('shot_', 'Shot '), sublabel: `${sh.duration_s}s · ${sh.camera?.shot_size || 'MS'}`,
      kind: 'shot', status: latestRun?.status || sh.status, videoUrl: latestRun?.output_video_signed_url,
      details: {
        Scene: sh.scene_id, Duration: `${sh.duration_s}s`,
        Camera: `${sh.camera?.shot_size || ''} ${sh.camera?.movement || ''} (${sh.camera?.lens_mm || 35}mm)`,
        Action: (sh.beats || []).map((b) => b.description).join(' | '),
        RenderStatus: latestRun ? `${latestRun.status} (Attempt #${latestRun.attempt})` : 'Not rendered yet',
      },
      x: Math.cos(angle) * 280, y: 155 + (idx % 2) * 25, z: Math.sin(angle) * 280, vx: 0, vy: 0, vz: 0,
      radius: KIND_META.shot.baseRadius, color: isApproved ? '#10b981' : KIND_META.shot.color,
      glowColor: isApproved ? 'rgba(16, 185, 129, 0.55)' : KIND_META.shot.glow,
    })
    addShotEdges(sh, edges)
  })
}

function applyRepulsionStep(nodes: GraphNode3D[]) {
  for (let i = 0; i < nodes.length; i++) {
    for (let j = i + 1; j < nodes.length; j++) {
      const a = nodes[i]
      const b = nodes[j]
      const dx = b.x - a.x
      const dy = b.y - a.y
      const dz = b.z - a.z
      const distSq = dx * dx + dy * dy + dz * dz + 100
      const dist = Math.sqrt(distSq)
      const force = 2600 / distSq
      if (a.kind !== 'style') {
        a.vx -= (dx / dist) * force
        a.vy -= (dy / dist) * force * 0.4
        a.vz -= (dz / dist) * force
      }
      if (b.kind !== 'style') {
        b.vx += (dx / dist) * force
        b.vy += (dy / dist) * force * 0.4
        b.vz += (dz / dist) * force
      }
    }
  }
}

function applySpringAndIntegrateStep(
  nodes: GraphNode3D[],
  edges: GraphEdge3D[],
  nodeById: Record<string, GraphNode3D>,
) {
  for (const e of edges) {
    const s = nodeById[e.source]
    const t = nodeById[e.target]
    if (!s || !t) continue
    const dx = t.x - s.x
    const dy = t.y - s.y
    const dz = t.z - s.z
    const dist = Math.sqrt(dx * dx + dy * dy + dz * dz) || 1
    const diff = (dist - 135) * 0.025
    if (s.kind !== 'style') {
      s.vx += (dx / dist) * diff
      s.vy += (dy / dist) * diff * 0.3
      s.vz += (dz / dist) * diff
    }
    if (t.kind !== 'style') {
      t.vx -= (dx / dist) * diff
      t.vy -= (dy / dist) * diff * 0.3
      t.vz -= (dz / dist) * diff
    }
  }
  for (const n of nodes) {
    if (n.kind === 'style') continue
    n.x += n.vx * 0.35
    n.y += n.vy * 0.35
    n.z += n.vz * 0.35
    n.vx *= 0.6
    n.vy *= 0.6
    n.vz *= 0.6
  }
}

export function buildStoryGraph3D(storyGraph?: StoryGraphData): {
  nodes: GraphNode3D[]
  edges: GraphEdge3D[]
} {
  const builtNodes: GraphNode3D[] = []
  const builtEdges: GraphEdge3D[] = []
  if (!storyGraph) return { nodes: builtNodes, edges: builtEdges }

  const sg = storyGraph.style_guide
  const appearances = (storyGraph.appearances || []).filter((a) => a.status !== 'superseded')
  const { entityPrimaryImg, appearanceImg } = buildImageLookups(appearances)
  const styleId = sg?.id || 'style_global'

  builtNodes.push({
    id: styleId,
    label: 'Style Bible',
    sublabel: sg?.visual_medium?.slice(0, 36) || 'Global Visual Style',
    kind: 'style',
    status: 'approved',
    details: {
      Medium: sg?.visual_medium || 'Cinematic',
      Lighting: sg?.lighting_rules || '',
      Lens: sg?.lens_language || '',
      Palette: (sg?.palette || []).join(', '),
    },
    x: 0,
    y: 0,
    z: 0,
    vx: 0,
    vy: 0,
    vz: 0,
    radius: KIND_META.style.baseRadius,
    color: KIND_META.style.color,
    glowColor: KIND_META.style.glow,
  })

  addEntityRingNodes(storyGraph.entities?.characters || [], 'character', styleId, 'rgba(16, 185, 129, 0.35)', entityPrimaryImg, builtNodes, builtEdges)
  addEntityRingNodes(storyGraph.entities?.locations || [], 'location', styleId, 'rgba(139, 92, 246, 0.35)', entityPrimaryImg, builtNodes, builtEdges)
  addEntityRingNodes(storyGraph.entities?.objects || [], 'object', styleId, 'rgba(236, 72, 153, 0.35)', entityPrimaryImg, builtNodes, builtEdges)
  addAppearanceAndSceneNodes(appearances, storyGraph.scenes || [], storyGraph.events || [], appearanceImg, builtNodes, builtEdges)
  addShotNodes(storyGraph.shots || [], storyGraph.generation_runs || [], builtNodes, builtEdges)

  const nodeById: Record<string, GraphNode3D> = {}
  for (const n of builtNodes) nodeById[n.id] = n
  for (let step = 0; step < 45; step++) {
    applyRepulsionStep(builtNodes)
    applySpringAndIntegrateStep(builtNodes, builtEdges, nodeById)
  }

  return { nodes: builtNodes, edges: builtEdges }
}
