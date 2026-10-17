import type { GraphNode3D, GraphEdge3D } from './graphBuilder3D'

export interface ProjectedNodeItem {
  node: GraphNode3D
  sx: number
  sy: number
  scale: number
  depth: number
  sr: number
}

export function createProjector3D(
  cx: number,
  cy: number,
  yaw: number,
  pitch: number,
  zoom: number,
) {
  const cosY = Math.cos(yaw)
  const sinY = Math.sin(yaw)
  const cosP = Math.cos(pitch)
  const sinP = Math.sin(pitch)
  const fov = 560 * zoom

  return (x: number, y: number, z: number) => {
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
}

export function drawBackgroundAndRings(
  ctx: CanvasRenderingContext2D,
  w: number,
  h: number,
  project3D: ReturnType<typeof createProjector3D>,
) {
  const cx = w / 2
  const cy = h / 2
  const bgGrad = ctx.createRadialGradient(cx, cy, 20, cx, cy, Math.max(w, h) * 0.75)
  bgGrad.addColorStop(0, '#131826')
  bgGrad.addColorStop(0.55, '#0b0f19')
  bgGrad.addColorStop(1, '#06080f')
  ctx.fillStyle = bgGrad
  ctx.fillRect(0, 0, w, h)

  ;[155, 225, 285].forEach((ringR, rIdx) => {
    ctx.beginPath()
    for (let i = 0; i <= 64; i++) {
      const a = (i / 64) * Math.PI * 2
      const ry = rIdx === 0 ? -65 : rIdx === 1 ? 15 : 135
      const p = project3D(Math.cos(a) * ringR, ry, Math.sin(a) * ringR)
      if (i === 0) ctx.moveTo(p.sx, p.sy)
      else ctx.lineTo(p.sx, p.sy)
    }
    ctx.strokeStyle = 'rgba(148, 163, 184, 0.08)'
    ctx.lineWidth = 1
    ctx.stroke()
  })
}

export function drawGraphEdges3D(
  ctx: CanvasRenderingContext2D,
  visibleEdges: GraphEdge3D[],
  projMap: Record<string, ProjectedNodeItem>,
  activeFocusId: string | null,
  tick: number,
) {
  for (let eIdx = 0; eIdx < visibleEdges.length; eIdx++) {
    const edge = visibleEdges[eIdx]
    const s = projMap[edge.source]
    const t = projMap[edge.target]
    if (!s || !t) continue

    const isHighlighted =
      Boolean(activeFocusId) && (edge.source === activeFocusId || edge.target === activeFocusId)
    const isDimmed = Boolean(activeFocusId) && !isHighlighted

    ctx.beginPath()
    const mx = (s.sx + t.sx) / 2
    const my = (s.sy + t.sy) / 2 - 14 * ((s.scale + t.scale) * 0.5)
    ctx.moveTo(s.sx, s.sy)
    ctx.quadraticCurveTo(mx, my, t.sx, t.sy)
    ctx.strokeStyle = isHighlighted ? '#38bdf8' : isDimmed ? 'rgba(148, 163, 184, 0.07)' : edge.color
    ctx.lineWidth = isHighlighted ? 2.2 : 1.15
    ctx.stroke()

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
}

function drawNodeSphereAndThumb(
  ctx: CanvasRenderingContext2D,
  item: ProjectedNodeItem,
  isSelected: boolean,
  isHovered: boolean,
  tick: number,
  imageCache: Record<string, HTMLImageElement>,
) {
  const { node, sx, sy, sr } = item
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

  ctx.beginPath()
  ctx.arc(sx, sy, sr, 0, Math.PI * 2)
  const sphereGrad = ctx.createRadialGradient(sx - sr * 0.35, sy - sr * 0.35, sr * 0.1, sx, sy, sr)
  sphereGrad.addColorStop(0, '#ffffff')
  sphereGrad.addColorStop(0.25, node.color)
  sphereGrad.addColorStop(1, '#090d16')
  ctx.fillStyle = sphereGrad
  ctx.fill()

  const cachedImg = node.imageUrl ? imageCache[node.imageUrl] : null
  if (cachedImg && cachedImg.complete && cachedImg.naturalWidth > 0 && sr > 9) {
    ctx.save()
    ctx.beginPath()
    ctx.arc(sx, sy, Math.max(4, sr - 2.2), 0, Math.PI * 2)
    ctx.clip()
    ctx.drawImage(cachedImg, sx - sr, sy - sr, sr * 2, sr * 2)
    ctx.restore()
  }
}

export function drawGraphNodes3D(
  ctx: CanvasRenderingContext2D,
  sortedProj: ProjectedNodeItem[],
  selectedNodeId: string | null,
  hoveredNodeId: string | null,
  connectedNeighbors: Set<string>,
  tick: number,
  imageCache: Record<string, HTMLImageElement>,
) {
  const activeFocusId = selectedNodeId || hoveredNodeId
  for (const item of sortedProj) {
    const { node, sx, sy, sr } = item
    const isSelected = node.id === selectedNodeId
    const isHovered = node.id === hoveredNodeId
    const isDimmed = Boolean(activeFocusId) && !connectedNeighbors.has(node.id)

    ctx.save()
    ctx.globalAlpha = isDimmed ? 0.22 : 1.0
    drawNodeSphereAndThumb(ctx, item, isSelected, isHovered, tick, imageCache)

    ctx.beginPath()
    ctx.arc(sx, sy, sr, 0, Math.PI * 2)
    ctx.lineWidth = isSelected ? 3 : isHovered ? 2.4 : 1.6
    ctx.strokeStyle = isSelected ? '#ffffff' : node.status === 'approved' ? '#34d399' : node.color
    ctx.stroke()

    if (sr > 8 || isSelected || isHovered) {
      ctx.font = `${isSelected || isHovered ? 'bold ' : ''}11px ui-monospace, SFMono-Regular, Menlo, monospace`
      const text = node.label
      const textW = ctx.measureText(text).width
      const pillX = sx - textW / 2 - 6
      const pillY = sy + sr + 5
      ctx.fillStyle = isSelected ? 'rgba(14, 165, 233, 0.9)' : 'rgba(15, 23, 42, 0.82)'
      ctx.beginPath()
      ctx.roundRect(pillX, pillY, textW + 12, 17, 4)
      ctx.fill()
      ctx.fillStyle = '#f8fafc'
      ctx.fillText(text, sx - textW / 2, pillY + 12)
    }
    ctx.restore()
  }
}
