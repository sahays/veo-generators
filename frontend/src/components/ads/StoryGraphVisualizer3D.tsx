import React, { useEffect, useRef, useState, useMemo } from 'react'
import {
  Orbit,
  ZoomIn,
  ZoomOut,
  RotateCcw,
  Sparkles,
  User,
  MapPin,
  Box,
  Film,
  Layers,
  CheckCircle2,
  RefreshCw,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/Common'
import type { StoryGraphData } from '@/types/project'

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

interface StoryGraphVisualizer3DProps {
  storyGraph?: StoryGraphData
  canWrite?: boolean
  onApproveAppearance?: (appearanceId: string) => void
  onRegenerateAppearance?: (appearanceId: string) => void
}

const KIND_META: Record<
  GraphNodeKind,
  { label: string; color: string; glow: string; baseRadius: number }
> = {
  style: {
    label: 'Style Guide',
    color: '#f59e0b',
    glow: 'rgba(245, 158, 11, 0.55)',
    baseRadius: 24,
  },
  character: {
    label: 'Character',
    color: '#10b981',
    glow: 'rgba(16, 185, 129, 0.5)',
    baseRadius: 19,
  },
  location: {
    label: 'Location',
    color: '#8b5cf6',
    glow: 'rgba(139, 92, 246, 0.5)',
    baseRadius: 19,
  },
  object: {
    label: 'Prop / Object',
    color: '#ec4899',
    glow: 'rgba(236, 72, 153, 0.5)',
    baseRadius: 16,
  },
  scene: {
    label: 'Scene',
    color: '#3b82f6',
    glow: 'rgba(59, 130, 246, 0.5)',
    baseRadius: 18,
  },
  event: {
    label: 'Story Event',
    color: '#06b6d4',
    glow: 'rgba(6, 182, 212, 0.45)',
    baseRadius: 13,
  },
  appearance: {
    label: 'Design Sheet',
    color: '#eab308',
    glow: 'rgba(234, 179, 8, 0.45)',
    baseRadius: 15,
  },
  shot: {
    label: 'Rendered Shot',
    color: '#f43f5e',
    glow: 'rgba(244, 63, 94, 0.5)',
    baseRadius: 17,
  },
}

export const StoryGraphVisualizer3D: React.FC<StoryGraphVisualizer3DProps> = ({
  storyGraph,
  canWrite = false,
  onApproveAppearance,
  onRegenerateAppearance,
}) => {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null)
  const [autoRotate, setAutoRotate] = useState<boolean>(true)
  const [kindFilter, setKindFilter] = useState<GraphNodeKind | 'all'>('all')
  const [zoom, setZoom] = useState<number>(1.0)

  const rotationRef = useRef<{ yaw: number; pitch: number }>({ yaw: 0.45, pitch: 0.28 })
  const isDraggingRef = useRef<boolean>(false)
  const lastMouseRef = useRef<{ x: number; y: number }>({ x: 0, y: 0 })
  const imageCacheRef = useRef<Record<string, HTMLImageElement>>({})
  const projectedNodesRef = useRef<
    Array<{ id: string; sx: number; sy: number; sr: number; depth: number }>
  >([])

  const { nodes, edges } = useMemo(() => {
    const builtNodes: GraphNode3D[] = []
    const builtEdges: GraphEdge3D[] = []
    if (!storyGraph) return { nodes: builtNodes, edges: builtEdges }

    const sg = storyGraph.style_guide
    const characters = storyGraph.entities?.characters || []
    const locations = storyGraph.entities?.locations || []
    const objects = storyGraph.entities?.objects || []
    const scenes = storyGraph.scenes || []
    const events = storyGraph.events || []
    const appearances = (storyGraph.appearances || []).filter(
      (a: any) => a.status !== 'superseded',
    )
    const shots = storyGraph.shots || []
    const runs = storyGraph.generation_runs || []

    const latestRunByShot: Record<string, any> = {}
    for (const r of runs) {
      if (!latestRunByShot[r.shot_id] || r.attempt >= latestRunByShot[r.shot_id].attempt) {
        latestRunByShot[r.shot_id] = r
      }
    }

    // Primary appearance image lookup by entity_id and appearance_id
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

    // 1. Central StyleGuide Core
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

    // 2. Characters (Inner Ring, upper hemisphere)
    characters.forEach((ch: any, idx: number) => {
      const angle = (idx / Math.max(1, characters.length)) * Math.PI * 2
      const r = 150
      const attrs: Record<string, string> = {}
      Object.entries(ch.attributes || {}).forEach(([k, v]: [string, any]) => {
        attrs[k] = typeof v === 'object' && v?.value ? String(v.value) : String(v)
      })
      builtNodes.push({
        id: ch.id,
        label: ch.canonical_name,
        sublabel: 'Character',
        kind: 'character',
        status: ch.status,
        imageUrl: entityPrimaryImg[ch.id],
        details: attrs,
        x: Math.cos(angle) * r,
        y: -70 + (idx % 2) * 30,
        z: Math.sin(angle) * r,
        vx: 0,
        vy: 0,
        vz: 0,
        radius: KIND_META.character.baseRadius,
        color: KIND_META.character.color,
        glowColor: KIND_META.character.glow,
      })
      builtEdges.push({
        id: `e_${styleId}_${ch.id}`,
        source: styleId,
        target: ch.id,
        label: 'styles',
        color: 'rgba(16, 185, 129, 0.35)',
      })
    })

    // 3. Locations (Mid Ring, equatorial plane)
    locations.forEach((loc: any, idx: number) => {
      const angle = (idx / Math.max(1, locations.length)) * Math.PI * 2 + 0.4
      const r = 185
      const attrs: Record<string, string> = {}
      Object.entries(loc.attributes || {}).forEach(([k, v]: [string, any]) => {
        attrs[k] = typeof v === 'object' && v?.value ? String(v.value) : String(v)
      })
      builtNodes.push({
        id: loc.id,
        label: loc.canonical_name,
        sublabel: 'Location',
        kind: 'location',
        status: loc.status,
        imageUrl: entityPrimaryImg[loc.id],
        details: attrs,
        x: Math.cos(angle) * r,
        y: 20,
        z: Math.sin(angle) * r,
        vx: 0,
        vy: 0,
        vz: 0,
        radius: KIND_META.location.baseRadius,
        color: KIND_META.location.color,
        glowColor: KIND_META.location.glow,
      })
      builtEdges.push({
        id: `e_${styleId}_${loc.id}`,
        source: styleId,
        target: loc.id,
        label: 'styles',
        color: 'rgba(139, 92, 246, 0.35)',
      })
    })

    // 4. Objects / Props
    objects.forEach((obj: any, idx: number) => {
      const angle = (idx / Math.max(1, objects.length)) * Math.PI * 2 + 1.1
      const r = 140
      builtNodes.push({
        id: obj.id,
        label: obj.canonical_name,
        sublabel: 'Hero Prop',
        kind: 'object',
        status: obj.status,
        imageUrl: entityPrimaryImg[obj.id],
        details: { Type: 'Hero Prop / Object', ID: obj.id },
        x: Math.cos(angle) * r,
        y: -115,
        z: Math.sin(angle) * r,
        vx: 0,
        vy: 0,
        vz: 0,
        radius: KIND_META.object.baseRadius,
        color: KIND_META.object.color,
        glowColor: KIND_META.object.glow,
      })
      builtEdges.push({
        id: `e_${styleId}_${obj.id}`,
        source: styleId,
        target: obj.id,
        label: 'styles',
        color: 'rgba(236, 72, 153, 0.35)',
      })
    })

    // 5. Appearances (Design Studio Reference Sheets orbiting their Entity)
    appearances.forEach((app: any, idx: number) => {
      const angle = (idx / Math.max(1, appearances.length)) * Math.PI * 2 + 0.25
      const r = 235
      builtNodes.push({
        id: app.id,
        label: `${app.entity_id.replace(/^(char_|loc_|obj_)/, '')} (${app.state_label})`,
        sublabel: `v${app.version} · ${app.status}`,
        kind: 'appearance',
        status: app.status,
        imageUrl: appearanceImg[app.id],
        appearanceId: app.id,
        details: {
          Entity: app.entity_id,
          State: app.state_label,
          Description: app.visual_description || '',
          Wardrobe: app.wardrobe || 'N/A',
          Status: app.status,
        },
        x: Math.cos(angle) * r,
        y: -45 + (idx % 3) * 35,
        z: Math.sin(angle) * r,
        vx: 0,
        vy: 0,
        vz: 0,
        radius: KIND_META.appearance.baseRadius,
        color: KIND_META.appearance.color,
        glowColor: KIND_META.appearance.glow,
      })
      builtEdges.push({
        id: `e_${app.entity_id}_${app.id}`,
        source: app.entity_id,
        target: app.id,
        label: app.state_label,
        color: 'rgba(234, 179, 8, 0.45)',
      })
    })

    // 6. Scenes & Events (Lower Spine)
    scenes.forEach((sc: any, idx: number) => {
      const angle = (idx / Math.max(1, scenes.length)) * Math.PI * 2
      const r = 170
      builtNodes.push({
        id: sc.id,
        label: `Scene ${sc.index || idx + 1}`,
        sublabel: sc.heading || sc.summary?.slice(0, 32) || sc.id,
        kind: 'scene',
        status: sc.status,
        details: {
          Heading: sc.heading || '',
          Time: sc.time_of_day || '',
          Summary: sc.summary || '',
          Location: sc.location_id || '',
        },
        x: Math.cos(angle) * r,
        y: 95,
        z: Math.sin(angle) * r,
        vx: 0,
        vy: 0,
        vz: 0,
        radius: KIND_META.scene.baseRadius,
        color: KIND_META.scene.color,
        glowColor: KIND_META.scene.glow,
      })
      if (sc.location_id) {
        builtEdges.push({
          id: `e_${sc.id}_${sc.location_id}`,
          source: sc.id,
          target: sc.location_id,
          label: 'set_at',
          color: 'rgba(59, 130, 246, 0.4)',
        })
      }
    })

    events.forEach((ev: any, idx: number) => {
      const angle = (idx / Math.max(1, events.length)) * Math.PI * 2 + 0.3
      const r = 215
      builtNodes.push({
        id: ev.id,
        label: `Event #${ev.story_order}`,
        sublabel: ev.summary?.slice(0, 36) || ev.id,
        kind: 'event',
        status: ev.status,
        details: {
          Order: String(ev.story_order),
          Scene: ev.scene_id,
          Summary: ev.summary || '',
          Participants: (ev.participant_ids || []).join(', '),
        },
        x: Math.cos(angle) * r,
        y: 125,
        z: Math.sin(angle) * r,
        vx: 0,
        vy: 0,
        vz: 0,
        radius: KIND_META.event.baseRadius,
        color: KIND_META.event.color,
        glowColor: KIND_META.event.glow,
      })
      if (ev.scene_id) {
        builtEdges.push({
          id: `e_${ev.scene_id}_${ev.id}`,
          source: ev.scene_id,
          target: ev.id,
          label: 'event',
          color: 'rgba(6, 182, 212, 0.4)',
        })
      }
    })

    // 7. Shots (Outer Orbital Ring)
    shots.forEach((sh: any, idx: number) => {
      const angle = (idx / Math.max(1, shots.length)) * Math.PI * 2
      const r = 280
      const latestRun = latestRunByShot[sh.id]
      builtNodes.push({
        id: sh.id,
        label: sh.id.replace('shot_', 'Shot '),
        sublabel: `${sh.duration_s}s · ${sh.camera?.shot_size || 'MS'}`,
        kind: 'shot',
        status: latestRun?.status || sh.status,
        videoUrl: latestRun?.output_video_signed_url,
        details: {
          Scene: sh.scene_id,
          Duration: `${sh.duration_s}s`,
          Camera: `${sh.camera?.shot_size || ''} ${sh.camera?.movement || ''} (${sh.camera?.lens_mm || 35}mm)`,
          Action: (sh.beats || []).map((b: any) => b.description).join(' | '),
          RenderStatus: latestRun ? `${latestRun.status} (Attempt #${latestRun.attempt})` : 'Not rendered yet',
        },
        x: Math.cos(angle) * r,
        y: 155 + (idx % 2) * 25,
        z: Math.sin(angle) * r,
        vx: 0,
        vy: 0,
        vz: 0,
        radius: KIND_META.shot.baseRadius,
        color: latestRun?.status === 'approved' ? '#10b981' : KIND_META.shot.color,
        glowColor:
          latestRun?.status === 'approved'
            ? 'rgba(16, 185, 129, 0.55)'
            : KIND_META.shot.glow,
      })
      if (sh.scene_id) {
        builtEdges.push({
          id: `e_${sh.scene_id}_${sh.id}`,
          source: sh.scene_id,
          target: sh.id,
          label: 'shot',
          color: 'rgba(244, 63, 94, 0.45)',
        })
      }
      for (const c of sh.cast || []) {
        if (c.appearance_id) {
          builtEdges.push({
            id: `e_${c.appearance_id}_${sh.id}`,
            source: c.appearance_id,
            target: sh.id,
            label: 'cast_ref',
            color: 'rgba(234, 179, 8, 0.3)',
          })
        } else if (c.entity_id) {
          builtEdges.push({
            id: `e_${c.entity_id}_${sh.id}`,
            source: c.entity_id,
            target: sh.id,
            label: 'cast',
            color: 'rgba(16, 185, 129, 0.3)',
          })
        }
      }
    })

    // Run 45 iterations of 3D force relaxation so nodes have organic spacing
    const nodeById: Record<string, GraphNode3D> = {}
    for (const n of builtNodes) nodeById[n.id] = n

    for (let step = 0; step < 45; step++) {
      // Repulsion
      for (let i = 0; i < builtNodes.length; i++) {
        for (let j = i + 1; j < builtNodes.length; j++) {
          const a = builtNodes[i]
          const b = builtNodes[j]
          const dx = b.x - a.x
          const dy = b.y - a.y
          const dz = b.z - a.z
          const distSq = dx * dx + dy * dy + dz * dz + 100
          const force = 2600 / distSq
          const dist = Math.sqrt(distSq)
          const fx = (dx / dist) * force
          const fy = (dy / dist) * force
          const fz = (dz / dist) * force
          if (a.kind !== 'style') {
            a.vx -= fx
            a.vy -= fy * 0.4
            a.vz -= fz
          }
          if (b.kind !== 'style') {
            b.vx += fx
            b.vy += fy * 0.4
            b.vz += fz
          }
        }
      }
      // Spring attraction along edges
      for (const e of builtEdges) {
        const s = nodeById[e.source]
        const t = nodeById[e.target]
        if (!s || !t) continue
        const dx = t.x - s.x
        const dy = t.y - s.y
        const dz = t.z - s.z
        const dist = Math.sqrt(dx * dx + dy * dy + dz * dz) || 1
        const targetDist = 135
        const diff = (dist - targetDist) * 0.025
        const fx = (dx / dist) * diff
        const fy = (dy / dist) * diff
        const fz = (dz / dist) * diff
        if (s.kind !== 'style') {
          s.vx += fx
          s.vy += fy * 0.3
          s.vz += fz
        }
        if (t.kind !== 'style') {
          t.vx -= fx
          t.vy -= fy * 0.3
          t.vz -= fz
        }
      }
      for (const n of builtNodes) {
        if (n.kind === 'style') continue
        n.x += n.vx * 0.35
        n.y += n.vy * 0.35
        n.z += n.vz * 0.35
        n.vx *= 0.6
        n.vy *= 0.6
        n.vz *= 0.6
      }
    }

    return { nodes: builtNodes, edges: builtEdges }
  }, [storyGraph])

  // Preload node images into HTMLImageElement cache for circular rendering inside 3D spheres
  useEffect(() => {
    for (const node of nodes) {
      if (node.imageUrl && !imageCacheRef.current[node.imageUrl]) {
        const img = new Image()
        img.crossOrigin = 'anonymous'
        img.src = node.imageUrl
        imageCacheRef.current[node.imageUrl] = img
      }
    }
  }, [nodes])

  const visibleNodes = useMemo(() => {
    if (kindFilter === 'all') return nodes
    return nodes.filter((n) => n.kind === kindFilter || n.kind === 'style')
  }, [nodes, kindFilter])

  const visibleNodeSet = useMemo(
    () => new Set(visibleNodes.map((n) => n.id)),
    [visibleNodes],
  )

  const visibleEdges = useMemo(
    () =>
      edges.filter(
        (e) => visibleNodeSet.has(e.source) && visibleNodeSet.has(e.target),
      ),
    [edges, visibleNodeSet],
  )

  const selectedNode = useMemo(
    () => nodes.find((n) => n.id === selectedNodeId) || null,
    [nodes, selectedNodeId],
  )

  const connectedNeighbors = useMemo(() => {
    const activeId = selectedNodeId || hoveredNodeId
    if (!activeId) return new Set<string>()
    const s = new Set<string>([activeId])
    for (const e of edges) {
      if (e.source === activeId) s.add(e.target)
      if (e.target === activeId) s.add(e.source)
    }
    return s
  }, [edges, selectedNodeId, hoveredNodeId])

  // Main 3D Canvas Render Loop
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    let animId = 0
    let tick = 0

    const render = () => {
      tick += 0.014
      if (autoRotate && !isDraggingRef.current) {
        rotationRef.current.yaw += 0.0038
      }

      const dpr = window.devicePixelRatio || 1
      const rect = canvas.getBoundingClientRect()
      if (canvas.width !== Math.floor(rect.width * dpr) || canvas.height !== Math.floor(rect.height * dpr)) {
        canvas.width = Math.floor(rect.width * dpr)
        canvas.height = Math.floor(rect.height * dpr)
      }

      ctx.save()
      ctx.scale(dpr, dpr)
      const w = rect.width
      const h = rect.height
      const cx = w / 2
      const cy = h / 2

      // Deep space studio background gradient
      const bgGrad = ctx.createRadialGradient(cx, cy, 20, cx, cy, Math.max(w, h) * 0.75)
      bgGrad.addColorStop(0, '#131826')
      bgGrad.addColorStop(0.55, '#0b0f19')
      bgGrad.addColorStop(1, '#06080f')
      ctx.fillStyle = bgGrad
      ctx.fillRect(0, 0, w, h)

      // Draw subtle 3D orbital rings
      const { yaw, pitch } = rotationRef.current
      const cosY = Math.cos(yaw)
      const sinY = Math.sin(yaw)
      const cosP = Math.cos(pitch)
      const sinP = Math.sin(pitch)
      const fov = 560 * zoom

      const project3D = (x: number, y: number, z: number) => {
        const x1 = x * cosY - z * sinY
        const z1 = z * cosY + x * sinY
        const y2 = y * cosP - z1 * sinP
        const z2 = z1 * cosP + y * sinP
        const depth = Math.max(120, 620 + z2)
        const scale = fov / depth
        return {
          sx: cx + x1 * scale,
          sy: cy + y2 * scale,
          scale,
          depth: z2,
        }
      }

      // Orbital reference rings
      ;[155, 225, 285].forEach((ringR, rIdx) => {
        ctx.beginPath()
        for (let i = 0; i <= 64; i++) {
          const a = (i / 64) * Math.PI * 2
          const rx = Math.cos(a) * ringR
          const rz = Math.sin(a) * ringR
          const ry = rIdx === 0 ? -65 : rIdx === 1 ? 15 : 135
          const p = project3D(rx, ry, rz)
          if (i === 0) ctx.moveTo(p.sx, p.sy)
          else ctx.lineTo(p.sx, p.sy)
        }
        ctx.strokeStyle = 'rgba(148, 163, 184, 0.08)'
        ctx.lineWidth = 1
        ctx.stroke()
      })

      // Project all visible nodes
      const projMap: Record<
        string,
        { node: GraphNode3D; sx: number; sy: number; scale: number; depth: number; sr: number }
      > = {}

      for (const n of visibleNodes) {
        const p = project3D(n.x, n.y, n.z)
        projMap[n.id] = {
          node: n,
          sx: p.sx,
          sy: p.sy,
          scale: p.scale,
          depth: p.depth,
          sr: Math.max(7, n.radius * p.scale),
        }
      }

      const activeFocusId = selectedNodeId || hoveredNodeId

      // Draw 3D Edges & Flowing Energy Particles
      for (let eIdx = 0; eIdx < visibleEdges.length; eIdx++) {
        const edge = visibleEdges[eIdx]
        const s = projMap[edge.source]
        const t = projMap[edge.target]
        if (!s || !t) continue

        const isHighlighted =
          activeFocusId && (edge.source === activeFocusId || edge.target === activeFocusId)
        const isDimmed = activeFocusId && !isHighlighted

        ctx.beginPath()
        const mx = (s.sx + t.sx) / 2
        const my = (s.sy + t.sy) / 2 - 14 * ((s.scale + t.scale) * 0.5)
        ctx.moveTo(s.sx, s.sy)
        ctx.quadraticCurveTo(mx, my, t.sx, t.sy)
        ctx.strokeStyle = isHighlighted
          ? '#38bdf8'
          : isDimmed
            ? 'rgba(148, 163, 184, 0.07)'
            : edge.color
        ctx.lineWidth = isHighlighted ? 2.2 : 1.15
        ctx.stroke()

        // Animated energy particle along edge
        if (!isDimmed) {
          const u = (tick * 0.55 + (eIdx * 0.19) % 1) % 1
          const px = (1 - u) * (1 - u) * s.sx + 2 * (1 - u) * u * mx + u * u * t.sx
          const py = (1 - u) * (1 - u) * s.sy + 2 * (1 - u) * u * my + u * u * t.sy
          ctx.beginPath()
          ctx.arc(px, py, isHighlighted ? 3.2 : 2.0, 0, Math.PI * 2)
          ctx.fillStyle = isHighlighted ? '#7dd3fc' : 'rgba(255, 255, 255, 0.7)'
          ctx.fill()
        }
      }

      // Sort nodes back-to-front (largest depth z2 first)
      const sortedProj = Object.values(projMap).sort((a, b) => b.depth - a.depth)
      projectedNodesRef.current = sortedProj.map((p) => ({
        id: p.node.id,
        sx: p.sx,
        sy: p.sy,
        sr: p.sr,
        depth: p.depth,
      }))

      // Draw Nodes
      for (const item of sortedProj) {
        const { node, sx, sy, sr } = item
        const isSelected = node.id === selectedNodeId
        const isHovered = node.id === hoveredNodeId
        const isConnected = connectedNeighbors.has(node.id)
        const isDimmed = activeFocusId && !isConnected

        ctx.save()
        ctx.globalAlpha = isDimmed ? 0.22 : 1.0

        // Outer glow halo
        if (isSelected || isHovered || node.kind === 'style') {
          const pulse = 1 + Math.sin(tick * 3) * 0.12
          const glowGrad = ctx.createRadialGradient(sx, sy, sr * 0.4, sx, sy, sr * 2.5 * pulse)
          glowGrad.addColorStop(0, node.glowColor)
          glowGrad.addColorStop(1, 'rgba(0,0,0,0)')
          ctx.fillStyle = glowGrad
          ctx.beginPath()
          ctx.arc(sx, sy, sr * 2.5 * pulse, 0, Math.PI * 2)
          ctx.fill()
        }

        // Node body sphere
        ctx.beginPath()
        ctx.arc(sx, sy, sr, 0, Math.PI * 2)
        const sphereGrad = ctx.createRadialGradient(
          sx - sr * 0.35,
          sy - sr * 0.35,
          sr * 0.1,
          sx,
          sy,
          sr,
        )
        sphereGrad.addColorStop(0, '#ffffff')
        sphereGrad.addColorStop(0.25, node.color)
        sphereGrad.addColorStop(1, '#090d16')
        ctx.fillStyle = sphereGrad
        ctx.fill()

        // If node has a preloaded reference sheet thumbnail, render it clipped inside the sphere
        const cachedImg = node.imageUrl ? imageCacheRef.current[node.imageUrl] : null
        if (cachedImg && cachedImg.complete && cachedImg.naturalWidth > 0 && sr > 9) {
          ctx.save()
          ctx.beginPath()
          ctx.arc(sx, sy, Math.max(4, sr - 2.2), 0, Math.PI * 2)
          ctx.clip()
          ctx.drawImage(cachedImg, sx - sr, sy - sr, sr * 2, sr * 2)
          ctx.restore()
        }

        // Border ring
        ctx.beginPath()
        ctx.arc(sx, sy, sr, 0, Math.PI * 2)
        ctx.lineWidth = isSelected ? 3 : isHovered ? 2.4 : 1.6
        ctx.strokeStyle = isSelected
          ? '#ffffff'
          : node.status === 'approved'
            ? '#34d399'
            : node.color
        ctx.stroke()

        // Node label pill
        if (sr > 8 || isSelected || isHovered) {
          ctx.font = `${isSelected || isHovered ? 'bold ' : ''}11px ui-monospace, SFMono-Regular, Menlo, monospace`
          const text = node.label
          const textW = ctx.measureText(text).width
          const pillX = sx - textW / 2 - 6
          const pillY = sy + sr + 5
          ctx.fillStyle = isSelected
            ? 'rgba(14, 165, 233, 0.9)'
            : 'rgba(15, 23, 42, 0.82)'
          ctx.beginPath()
          ctx.roundRect(pillX, pillY, textW + 12, 17, 4)
          ctx.fill()
          ctx.fillStyle = '#f8fafc'
          ctx.fillText(text, sx - textW / 2, pillY + 12)
        }

        ctx.restore()
      }

      ctx.restore()
      animId = window.requestAnimationFrame(render)
    }

    animId = window.requestAnimationFrame(render)
    return () => window.cancelAnimationFrame(animId)
  }, [
    visibleNodes,
    visibleEdges,
    autoRotate,
    zoom,
    selectedNodeId,
    hoveredNodeId,
    connectedNeighbors,
  ])

  const handleMouseDown = (e: React.MouseEvent<HTMLCanvasElement>) => {
    isDraggingRef.current = true
    lastMouseRef.current = { x: e.clientX, y: e.clientY }
  }

  const handleMouseMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current
    if (!canvas) return
    const rect = canvas.getBoundingClientRect()
    const mx = e.clientX - rect.left
    const my = e.clientY - rect.top

    if (isDraggingRef.current) {
      const dx = e.clientX - lastMouseRef.current.x
      const dy = e.clientY - lastMouseRef.current.y
      rotationRef.current.yaw += dx * 0.007
      rotationRef.current.pitch = Math.max(
        -1.25,
        Math.min(1.25, rotationRef.current.pitch + dy * 0.007),
      )
      lastMouseRef.current = { x: e.clientX, y: e.clientY }
      return
    }

    // Hit test front-to-back (reverse of sorted back-to-front)
    const list = projectedNodesRef.current
    let hit: string | null = null
    for (let i = list.length - 1; i >= 0; i--) {
      const item = list[i]
      const dx = mx - item.sx
      const dy = my - item.sy
      if (dx * dx + dy * dy <= (item.sr + 5) * (item.sr + 5)) {
        hit = item.id
        break
      }
    }
    if (hit !== hoveredNodeId) {
      setHoveredNodeId(hit)
    }
  }

  const handleMouseUp = (e: React.MouseEvent<HTMLCanvasElement>) => {
    isDraggingRef.current = false
    const canvas = canvasRef.current
    if (!canvas) return
    const rect = canvas.getBoundingClientRect()
    const mx = e.clientX - rect.left
    const my = e.clientY - rect.top

    const list = projectedNodesRef.current
    for (let i = list.length - 1; i >= 0; i--) {
      const item = list[i]
      const dx = mx - item.sx
      const dy = my - item.sy
      if (dx * dx + dy * dy <= (item.sr + 6) * (item.sr + 6)) {
        setSelectedNodeId((prev) => (prev === item.id ? null : item.id))
        return
      }
    }
  }

  return (
    <div className="glass rounded-xl border border-border/70 overflow-hidden">
      {/* Top 3D Controls & Filter Bar */}
      <div className="px-4 py-3 border-b border-border/60 flex flex-wrap items-center justify-between gap-3 bg-card/60">
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex items-center gap-1.5 mr-2">
            <Orbit size={16} className="text-accent-dark" />
            <span className="text-xs font-bold uppercase tracking-wider text-foreground">
              Interactive 3D StoryGraph Constellation
            </span>
            <span className="px-2 py-0.5 rounded bg-accent/10 text-accent-dark text-[10px] font-mono">
              {nodes.length} Nodes · {edges.length} Edges
            </span>
          </div>

          {(
            [
              { id: 'all', label: 'All Layers' },
              { id: 'character', label: 'Characters' },
              { id: 'location', label: 'Locations' },
              { id: 'object', label: 'Objects' },
              { id: 'appearance', label: 'Design Sheets' },
              { id: 'scene', label: 'Scenes' },
              { id: 'shot', label: 'Shots' },
            ] as const
          ).map((f) => (
            <Button
              key={f.id}
              size="xs"
              variant={kindFilter === f.id ? 'primary' : 'ghost'}
              onClick={() => setKindFilter(f.id)}
            >
              {f.label}
            </Button>
          ))}
        </div>

        <div className="flex items-center gap-1.5">
          <Button
            size="xs"
            variant={autoRotate ? 'primary' : 'outline'}
            icon={Orbit}
            onClick={() => setAutoRotate((v) => !v)}
          >
            {autoRotate ? 'Orbiting' : 'Paused'}
          </Button>
          <Button
            size="xs"
            variant="outline"
            icon={ZoomIn}
            onClick={() => setZoom((z) => Math.min(2.2, +(z + 0.2).toFixed(2)))}
          >
            Zoom In
          </Button>
          <Button
            size="xs"
            variant="outline"
            icon={ZoomOut}
            onClick={() => setZoom((z) => Math.max(0.55, +(z - 0.2).toFixed(2)))}
          >
            Zoom Out
          </Button>
          <Button
            size="xs"
            variant="ghost"
            icon={RotateCcw}
            onClick={() => {
              rotationRef.current = { yaw: 0.45, pitch: 0.28 }
              setZoom(1.0)
              setSelectedNodeId(null)
            }}
          >
            Reset
          </Button>
        </div>
      </div>

      {/* Main 3D Viewport + Inspector Split */}
      <div className="grid grid-cols-1 lg:grid-cols-12">
        <div
          className={cn(
            'relative h-[480px] select-none',
            selectedNode ? 'lg:col-span-8' : 'lg:col-span-12',
          )}
        >
          <canvas
            ref={canvasRef}
            onMouseDown={handleMouseDown}
            onMouseMove={handleMouseMove}
            onMouseUp={handleMouseUp}
            onMouseLeave={() => {
              isDraggingRef.current = false
              setHoveredNodeId(null)
            }}
            className="w-full h-full cursor-grab active:cursor-grabbing block"
          />

          {/* Floating Legend Overlay */}
          <div className="absolute bottom-3 left-3 flex flex-wrap items-center gap-2 px-3 py-2 rounded-lg bg-black/75 border border-white/10 backdrop-blur-md text-[10px] font-mono text-slate-200 pointer-events-none">
            {(Object.entries(KIND_META) as Array<[GraphNodeKind, (typeof KIND_META)['style']]>).map(
              ([k, meta]) => (
                <span key={k} className="inline-flex items-center gap-1.5">
                  <span
                    className="w-2.5 h-2.5 rounded-full inline-block"
                    style={{ backgroundColor: meta.color }}
                  />
                  <span>{meta.label}</span>
                </span>
              ),
            )}
            <span className="text-slate-400 ml-2">
              Drag to rotate 3D · Click any node to inspect
            </span>
          </div>
        </div>

        {/* Selected Node Inspector Drawer */}
        {selectedNode && (
          <div className="lg:col-span-4 border-t lg:border-t-0 lg:border-l border-border/60 bg-card/90 p-4 flex flex-col justify-between space-y-4 max-h-[480px] overflow-y-auto">
            <div className="space-y-3">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <span
                    className="inline-block px-2 py-0.5 rounded text-[9px] font-mono font-bold uppercase text-white mb-1"
                    style={{ backgroundColor: selectedNode.color }}
                  >
                    {KIND_META[selectedNode.kind].label}
                  </span>
                  <h4 className="text-sm font-bold text-foreground">{selectedNode.label}</h4>
                  <p className="text-[11px] font-mono text-muted-foreground">
                    ID: {selectedNode.id} · {selectedNode.sublabel}
                  </p>
                </div>
                <Button
                  size="xs"
                  variant="ghost"
                  onClick={() => setSelectedNodeId(null)}
                >
                  Close
                </Button>
              </div>

              {selectedNode.imageUrl && (
                <div className="rounded-lg overflow-hidden border border-border/60 bg-black aspect-video">
                  <img
                    src={selectedNode.imageUrl}
                    alt={selectedNode.label}
                    className="w-full h-full object-cover"
                  />
                </div>
              )}

              {selectedNode.videoUrl && (
                <div className="rounded-lg overflow-hidden border border-border/60 bg-black aspect-video">
                  <video
                    key={selectedNode.videoUrl}
                    src={selectedNode.videoUrl}
                    controls
                    preload="metadata"
                    className="w-full h-full"
                  />
                </div>
              )}

              {selectedNode.details && Object.keys(selectedNode.details).length > 0 && (
                <div className="space-y-1.5 pt-1">
                  {Object.entries(selectedNode.details).map(
                    ([k, v]) =>
                      v && (
                        <div
                          key={k}
                          className="p-2 rounded bg-muted/40 border border-border/50 text-xs"
                        >
                          <span className="text-[10px] font-mono uppercase text-muted-foreground block">
                            {k}
                          </span>
                          <span className="text-foreground break-words">{v}</span>
                        </div>
                      ),
                  )}
                </div>
              )}
            </div>

            {canWrite && selectedNode.appearanceId && (
              <div className="pt-3 border-t border-border/50 flex items-center gap-2">
                {selectedNode.status !== 'approved' && onApproveAppearance && (
                  <Button
                    size="xs"
                    variant="primary"
                    icon={CheckCircle2}
                    onClick={() => onApproveAppearance(selectedNode.appearanceId!)}
                  >
                    Approve Sheet
                  </Button>
                )}
                {onRegenerateAppearance && (
                  <Button
                    size="xs"
                    variant="outline"
                    icon={RefreshCw}
                    onClick={() => onRegenerateAppearance(selectedNode.appearanceId!)}
                  >
                    Regenerate Sheet
                  </Button>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
