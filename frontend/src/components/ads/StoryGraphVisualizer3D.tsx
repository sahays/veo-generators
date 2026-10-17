import React, { useEffect, useRef, useState, useMemo } from 'react'
import { cn } from '@/lib/utils'
import type { StoryGraphData } from '@/types/project'
import {
  buildStoryGraph3D,
  type GraphNodeKind,
  type GraphNode3D,
  type GraphEdge3D,
} from './storygraph/graphBuilder3D'
import {
  createProjector3D,
  drawBackgroundAndRings,
  drawGraphEdges3D,
  drawGraphNodes3D,
  type ProjectedNodeItem,
} from './storygraph/graphCanvasRenderer3D'
import {
  Visualizer3DToolbar,
  Visualizer3DLegend,
  Visualizer3DInspector,
} from './storygraph/Visualizer3DControls'

export type { GraphNodeKind, GraphNode3D, GraphEdge3D }

interface StoryGraphVisualizer3DProps {
  storyGraph?: StoryGraphData
  canWrite?: boolean
  onApproveAppearance?: (appearanceId: string) => void
  onRegenerateAppearance?: (appearanceId: string) => void
}

function hitTestProjectedNode(
  list: Array<{ id: string; sx: number; sy: number; sr: number }>,
  mx: number,
  my: number,
  padding: number,
): string | null {
  for (let i = list.length - 1; i >= 0; i--) {
    const item = list[i]
    const dx = mx - item.sx
    const dy = my - item.sy
    if (dx * dx + dy * dy <= (item.sr + padding) * (item.sr + padding)) {
      return item.id
    }
  }
  return null
}

interface RenderLoopParams {
  canvasRef: React.RefObject<HTMLCanvasElement>
  visibleNodes: GraphNode3D[]
  visibleEdges: GraphEdge3D[]
  autoRotate: boolean
  zoom: number
  selectedNodeId: string | null
  hoveredNodeId: string | null
  connectedNeighbors: Set<string>
  rotationRef: React.MutableRefObject<{ yaw: number; pitch: number }>
  isDraggingRef: React.MutableRefObject<boolean>
  imageCacheRef: React.MutableRefObject<Record<string, HTMLImageElement>>
  projectedNodesRef: React.MutableRefObject<Array<{ id: string; sx: number; sy: number; sr: number; depth: number }>>
}

function renderCanvasFrame3D(canvas: HTMLCanvasElement, ctx: CanvasRenderingContext2D, params: RenderLoopParams, tick: number) {
  if (params.autoRotate && !params.isDraggingRef.current) params.rotationRef.current.yaw += 0.0038
  const dpr = window.devicePixelRatio || 1
  const rect = canvas.getBoundingClientRect()
  if (canvas.width !== Math.floor(rect.width * dpr) || canvas.height !== Math.floor(rect.height * dpr)) {
    canvas.width = Math.floor(rect.width * dpr)
    canvas.height = Math.floor(rect.height * dpr)
  }
  ctx.save()
  ctx.scale(dpr, dpr)
  const project3D = createProjector3D(rect.width / 2, rect.height / 2, params.rotationRef.current.yaw, params.rotationRef.current.pitch, params.zoom)
  drawBackgroundAndRings(ctx, rect.width, rect.height, project3D)
  const projMap: Record<string, ProjectedNodeItem> = {}
  for (const n of params.visibleNodes) {
    const p = project3D(n.x, n.y, n.z)
    projMap[n.id] = { node: n, sx: p.sx, sy: p.sy, scale: p.scale, depth: p.depth, sr: Math.max(7, n.radius * p.scale) }
  }
  drawGraphEdges3D(ctx, params.visibleEdges, projMap, params.selectedNodeId || params.hoveredNodeId, tick)
  const sortedProj = Object.values(projMap).sort((a, b) => b.depth - a.depth)
  params.projectedNodesRef.current = sortedProj.map((p) => ({ id: p.node.id, sx: p.sx, sy: p.sy, sr: p.sr, depth: p.depth }))
  drawGraphNodes3D(ctx, sortedProj, params.selectedNodeId, params.hoveredNodeId, params.connectedNeighbors, tick, params.imageCacheRef.current)
  ctx.restore()
}

function useCanvas3DRenderLoop(params: RenderLoopParams) {
  useEffect(() => {
    const canvas = params.canvasRef.current
    const ctx = canvas?.getContext('2d')
    if (!canvas || !ctx) return
    let animId = 0
    let tick = 0
    const render = () => {
      tick += 0.014
      renderCanvasFrame3D(canvas, ctx, params, tick)
      animId = window.requestAnimationFrame(render)
    }
    animId = window.requestAnimationFrame(render)
    return () => window.cancelAnimationFrame(animId)
  }, [params])
}

function useFilteredGraph3D(
  storyGraph: StoryGraphData | undefined,
  kindFilter: GraphNodeKind | 'all',
  selectedNodeId: string | null,
  hoveredNodeId: string | null,
  imageCacheRef: React.MutableRefObject<Record<string, HTMLImageElement>>,
) {
  const { nodes, edges } = useMemo(() => buildStoryGraph3D(storyGraph), [storyGraph])
  useEffect(() => {
    for (const node of nodes) {
      if (node.imageUrl && !imageCacheRef.current[node.imageUrl]) {
        const img = new Image()
        img.crossOrigin = 'anonymous'
        img.src = node.imageUrl
        imageCacheRef.current[node.imageUrl] = img
      }
    }
  }, [nodes, imageCacheRef])
  const visibleNodes = useMemo(() => (kindFilter === 'all' ? nodes : nodes.filter((n) => n.kind === kindFilter || n.kind === 'style')), [nodes, kindFilter])
  const visibleNodeSet = useMemo(() => new Set(visibleNodes.map((n) => n.id)), [visibleNodes])
  const visibleEdges = useMemo(() => edges.filter((e) => visibleNodeSet.has(e.source) && visibleNodeSet.has(e.target)), [edges, visibleNodeSet])
  const selectedNode = useMemo(() => nodes.find((n) => n.id === selectedNodeId) || null, [nodes, selectedNodeId])
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
  return { nodes, edges, visibleNodes, visibleEdges, selectedNode, connectedNeighbors }
}

const Visualizer3DView = (p: {
  nodesCount: number; edgesCount: number; kindFilter: GraphNodeKind | 'all'
  setKindFilter: (k: GraphNodeKind | 'all') => void; autoRotate: boolean; setAutoRotate: React.Dispatch<React.SetStateAction<boolean>>
  setZoom: React.Dispatch<React.SetStateAction<number>>; onReset: () => void
  selectedNode: GraphNode3D | null; setSelectedNodeId: React.Dispatch<React.SetStateAction<string | null>>
  setHoveredNodeId: (id: string | null) => void; canvasRef: React.RefObject<HTMLCanvasElement>
  isDraggingRef: React.MutableRefObject<boolean>; lastMouseRef: React.MutableRefObject<{ x: number; y: number }>
  onMouseMove: (e: React.MouseEvent<HTMLCanvasElement>) => void; onMouseUp: (e: React.MouseEvent<HTMLCanvasElement>) => void
  canWrite: boolean; onApproveAppearance?: (id: string) => void; onRegenerateAppearance?: (id: string) => void
}) => (
  <div className="glass rounded-xl border border-border/70 overflow-hidden">
    <Visualizer3DToolbar
      nodeCount={p.nodesCount} edgeCount={p.edgesCount} kindFilter={p.kindFilter} onKindFilterChange={p.setKindFilter}
      autoRotate={p.autoRotate} onToggleAutoRotate={() => p.setAutoRotate((v) => !v)}
      onZoomIn={() => p.setZoom((z) => Math.min(2.2, +(z + 0.2).toFixed(2)))}
      onZoomOut={() => p.setZoom((z) => Math.max(0.55, +(z - 0.2).toFixed(2)))}
      onReset={p.onReset}
    />
    <div className="grid grid-cols-1 lg:grid-cols-12">
      <div className={cn('relative h-[480px] select-none', p.selectedNode ? 'lg:col-span-8' : 'lg:col-span-12')}>
        <canvas
          ref={p.canvasRef}
          onMouseDown={(e) => { p.isDraggingRef.current = true; p.lastMouseRef.current = { x: e.clientX, y: e.clientY } }}
          onMouseMove={p.onMouseMove}
          onMouseUp={p.onMouseUp}
          onMouseLeave={() => { p.isDraggingRef.current = false; p.setHoveredNodeId(null) }}
          className="w-full h-full cursor-grab active:cursor-grabbing block"
        />
        <Visualizer3DLegend />
      </div>
      {p.selectedNode && (
        <Visualizer3DInspector
          selectedNode={p.selectedNode} canWrite={p.canWrite} onClose={() => p.setSelectedNodeId(null)}
          onApproveAppearance={p.onApproveAppearance} onRegenerateAppearance={p.onRegenerateAppearance}
        />
      )}
    </div>
  </div>
)

function useCanvasPointerHandlers(
  canvasRef: React.RefObject<HTMLCanvasElement>,
  isDraggingRef: React.MutableRefObject<boolean>,
  lastMouseRef: React.MutableRefObject<{ x: number; y: number }>,
  rotationRef: React.MutableRefObject<{ yaw: number; pitch: number }>,
  projectedNodesRef: React.MutableRefObject<Array<{ id: string; sx: number; sy: number; sr: number; depth: number }>>,
  hoveredNodeId: string | null,
  setHoveredNodeId: (id: string | null) => void,
  setSelectedNodeId: React.Dispatch<React.SetStateAction<string | null>>,
) {
  const handleMouseMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const rect = canvasRef.current?.getBoundingClientRect()
    if (!rect) return
    if (isDraggingRef.current) {
      rotationRef.current.yaw += (e.clientX - lastMouseRef.current.x) * 0.007
      rotationRef.current.pitch = Math.max(-1.25, Math.min(1.25, rotationRef.current.pitch + (e.clientY - lastMouseRef.current.y) * 0.007))
      lastMouseRef.current = { x: e.clientX, y: e.clientY }
      return
    }
    const hit = hitTestProjectedNode(projectedNodesRef.current, e.clientX - rect.left, e.clientY - rect.top, 5)
    if (hit !== hoveredNodeId) setHoveredNodeId(hit)
  }
  const handleMouseUp = (e: React.MouseEvent<HTMLCanvasElement>) => {
    isDraggingRef.current = false
    const rect = canvasRef.current?.getBoundingClientRect()
    if (!rect) return
    const hit = hitTestProjectedNode(projectedNodesRef.current, e.clientX - rect.left, e.clientY - rect.top, 6)
    if (hit) setSelectedNodeId((prev) => (prev === hit ? null : hit))
  }
  return { handleMouseMove, handleMouseUp }
}

export const StoryGraphVisualizer3D: React.FC<StoryGraphVisualizer3DProps> = ({
  storyGraph, canWrite = false, onApproveAppearance, onRegenerateAppearance,
}) => {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null)
  const [autoRotate, setAutoRotate] = useState<boolean>(true)
  const [kindFilter, setKindFilter] = useState<GraphNodeKind | 'all'>('all')
  const [zoom, setZoom] = useState<number>(1.0)
  const rotationRef = useRef({ yaw: 0.45, pitch: 0.28 }), isDraggingRef = useRef(false), lastMouseRef = useRef({ x: 0, y: 0 })
  const imageCacheRef = useRef<Record<string, HTMLImageElement>>({}), projectedNodesRef = useRef<Array<{ id: string; sx: number; sy: number; sr: number; depth: number }>>([])
  const graph = useFilteredGraph3D(storyGraph, kindFilter, selectedNodeId, hoveredNodeId, imageCacheRef)
  useCanvas3DRenderLoop({ canvasRef, visibleNodes: graph.visibleNodes, visibleEdges: graph.visibleEdges, autoRotate, zoom, selectedNodeId, hoveredNodeId, connectedNeighbors: graph.connectedNeighbors, rotationRef, isDraggingRef, imageCacheRef, projectedNodesRef })
  const { handleMouseMove, handleMouseUp } = useCanvasPointerHandlers(canvasRef, isDraggingRef, lastMouseRef, rotationRef, projectedNodesRef, hoveredNodeId, setHoveredNodeId, setSelectedNodeId)

  return (
    <Visualizer3DView
      nodesCount={graph.nodes.length} edgesCount={graph.edges.length} kindFilter={kindFilter} setKindFilter={setKindFilter}
      autoRotate={autoRotate} setAutoRotate={setAutoRotate} setZoom={setZoom}
      onReset={() => { rotationRef.current = { yaw: 0.45, pitch: 0.28 }; setZoom(1.0); setSelectedNodeId(null) }}
      selectedNode={graph.selectedNode} setSelectedNodeId={setSelectedNodeId} setHoveredNodeId={setHoveredNodeId}
      canvasRef={canvasRef} isDraggingRef={isDraggingRef} lastMouseRef={lastMouseRef}
      onMouseMove={handleMouseMove} onMouseUp={handleMouseUp}
      canWrite={canWrite} onApproveAppearance={onApproveAppearance} onRegenerateAppearance={onRegenerateAppearance}
    />
  )
}
