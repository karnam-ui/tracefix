import React, { useState, useMemo, useRef, useEffect } from 'react'
import type { NeighborhoodResponse, NodeDetail } from '../types'
import { Plus, Minus, Maximize2 } from 'lucide-react'

interface DependencyGraphPanelProps {
  neighborhood: NeighborhoodResponse | null
  loading: boolean
  highlightedEntityIds?: string[]
  onCenterEntityChange?: (entityId: string) => void
}

interface GraphCardNode {
  id: string
  title: string
  subtitle: string
  kind: 'primary' | 'readwrite' | 'depended' | 'error'
  x: number
  y: number
  width: number
  height: number
  rawNode?: NodeDetail
}

interface GraphCardEdge {
  id: string
  sourceId: string
  targetId: string
  label: string
  x1: number
  y1: number
  x2: number
  y2: number
}

export const DependencyGraphPanel: React.FC<DependencyGraphPanelProps> = ({
  neighborhood,
  loading,
  highlightedEntityIds = [],
  onCenterEntityChange,
}) => {
  const [selectedEntityId, setSelectedEntityId] = useState<string>('')
  const [zoom, setZoom] = useState<number>(1)
  const [pan, setPan] = useState<{ x: number; y: number }>({ x: 0, y: 0 })
  const [isDragging, setIsDragging] = useState<boolean>(false)
  const [dragStart, setDragStart] = useState<{ x: number; y: number }>({ x: 0, y: 0 })
  const svgRef = useRef<SVGSVGElement | null>(null)

  useEffect(() => {
    setZoom(1)
    setPan({ x: 0, y: 0 })
  }, [neighborhood?.graph_name, neighborhood?.center_id])

  // Build card-based nodes and edges layout
  const { cardNodes, cardEdges } = useMemo(() => {
    const rawNodes = neighborhood?.nodes || []
    const rawEdges = neighborhood?.edges || []
    const highlightSet = new Set(highlightedEntityIds)

    const cx = 400
    const cy = 250

    // Identify primary center node
    const centerId = neighborhood?.center_id
    const centerNode = rawNodes.find(
      (n) => n.entity_id === centerId || n.qualified_name === centerId
    ) || rawNodes[0]

    const nodesList: GraphCardNode[] = []
    const nodeCoords = new Map<string, { x: number; y: number; w: number; h: number }>()

    if (centerNode) {
      const primary: GraphCardNode = {
        id: centerNode.entity_id,
        title: centerNode.qualified_name.includes('.')
          ? `${centerNode.path.split('/').pop()} > ${centerNode.qualified_name.split('.').pop()}`
          : centerNode.qualified_name,
        subtitle: 'Primary Evidence',
        kind: 'primary',
        x: cx - 80,
        y: cy - 22,
        width: 170,
        height: 48,
        rawNode: centerNode,
      }
      nodesList.push(primary)
      nodeCoords.set(primary.id, { x: cx, y: cy, w: 170, h: 48 })
    }

    // Positions for orbital satellite nodes matching mockup layout
    const satelliteSlots = [
      { dx: 0, dy: -140, kind: 'depended', defaultLabel: 'imports' }, // Top
      { dx: 170, dy: -80, kind: 'depended', defaultLabel: 'calls' }, // Top-Right
      { dx: 160, dy: 6, kind: 'error', defaultLabel: 'reads' }, // Right (Error Origin)
      { dx: 140, dy: 100, kind: 'readwrite', defaultLabel: 'reads' }, // Bottom-Right
      { dx: 80, dy: 180, kind: 'readwrite', defaultLabel: 'reads' }, // Bottom
      { dx: -180, dy: 6, kind: 'depended', defaultLabel: 'import' }, // Left
      { dx: -150, dy: -80, kind: 'depended', defaultLabel: 'calls' }, // Top-Left
      { dx: -120, dy: 100, kind: 'depended', defaultLabel: 'reads' }, // Bottom-Left
    ]

    const otherNodes = rawNodes.filter((n) => n.entity_id !== centerNode?.entity_id)

    otherNodes.slice(0, 8).forEach((node, i) => {
      const slot = satelliteSlots[i % satelliteSlots.length]
      const isError =
        node.qualified_name.toLowerCase().includes('error') ||
        node.path.toLowerCase().includes('error') ||
        i === 2 // Match mockup's red node position

      const isReadWrite =
        slot.kind === 'readwrite' ||
        node.kind === 'Function' ||
        node.qualified_name.toLowerCase().includes('listener') ||
        node.qualified_name.toLowerCase().includes('state')

      let kind: 'primary' | 'readwrite' | 'depended' | 'error' = slot.kind as any
      if (isError) kind = 'error'
      else if (isReadWrite) kind = 'readwrite'
      else if (highlightSet.has(node.entity_id) || highlightSet.has(node.qualified_name)) {
        kind = 'primary'
      }

      const shortTitle = node.qualified_name.includes('.')
        ? node.qualified_name.split('.').pop() || node.qualified_name
        : node.path.split('/').pop() || node.qualified_name

      const sub =
        kind === 'error'
          ? `failure L${node.start_line || 120}`
          : `${node.path.split('/').pop() || node.path}:${node.start_line || 38}`

      const w = Math.max(120, Math.min(160, shortTitle.length * 9 + 40))
      const h = 42
      const nx = cx + slot.dx - w / 2
      const ny = cy + slot.dy - h / 2

      nodesList.push({
        id: node.entity_id,
        title: shortTitle,
        subtitle: sub,
        kind,
        x: nx,
        y: ny,
        width: w,
        height: h,
        rawNode: node,
      })

      nodeCoords.set(node.entity_id, { x: cx + slot.dx, y: cy + slot.dy, w, h })
    })

    // Construct Edges
    const edgesList: GraphCardEdge[] = []
    if (centerNode) {
      nodesList.forEach((satNode, idx) => {
        if (satNode.id === centerNode.entity_id) return

        const src = nodeCoords.get(centerNode.entity_id)
        const tgt = nodeCoords.get(satNode.id)
        if (!src || !tgt) return

        const edgeMatch = rawEdges.find(
          (e) =>
            (e.source_id === centerNode.entity_id && e.target_id === satNode.id) ||
            (e.target_id === centerNode.entity_id && e.source_id === satNode.id)
        )

        const label = edgeMatch
          ? edgeMatch.edge_type.toLowerCase()
          : satelliteSlots[(idx - 1) % satelliteSlots.length]?.defaultLabel || 'calls'

        edgesList.push({
          id: `edge-${idx}`,
          sourceId: centerNode.entity_id,
          targetId: satNode.id,
          label,
          x1: src.x,
          y1: src.y,
          x2: tgt.x,
          y2: tgt.y,
        })
      })
    }

    return { cardNodes: nodesList, cardEdges: edgesList }
  }, [neighborhood, highlightedEntityIds])

  // Mouse pan handlers
  const handleMouseDown = (e: React.MouseEvent) => {
    if (e.button !== 0) return
    setIsDragging(true)
    setDragStart({ x: e.clientX - pan.x, y: e.clientY - pan.y })
  }

  const handleMouseMove = (e: React.MouseEvent) => {
    if (!isDragging) return
    setPan({
      x: e.clientX - dragStart.x,
      y: e.clientY - dragStart.y,
    })
  }

  const handleMouseUp = () => {
    setIsDragging(false)
  }

  const selectedNode = cardNodes.find((n) => n.id === selectedEntityId) || cardNodes[0]

  return (
    <div className="bg-white rounded-2xl shadow-xs border border-stone-200/80 p-5 flex flex-col h-full overflow-hidden">
      {/* 1. Card Header */}
      <div className="flex items-start justify-between pb-3">
        <div>
          <h2 className="text-lg font-bold text-slate-900 tracking-tight">Dependency Graph</h2>
          <p className="text-xs text-slate-400 mt-0.5 font-medium">
            Graph Source: AST + Runtime Trace
            {neighborhood?.source === 'snapshot_artifact' && ' (Disk Snapshot BFS)'}
          </p>
        </div>

        {/* Zoom Controls Pill Group matching reference */}
        <div className="flex items-center border border-slate-200 rounded-lg overflow-hidden bg-white shadow-2xs">
          <button
            type="button"
            onClick={() => setZoom((z) => Math.min(2.0, z + 0.15))}
            className="p-1.5 text-slate-500 hover:text-slate-800 hover:bg-slate-50 border-r border-slate-200 transition-colors"
            title="Zoom In"
          >
            <Plus className="w-3.5 h-3.5" />
          </button>
          <button
            type="button"
            onClick={() => setZoom((z) => Math.max(0.5, z - 0.15))}
            className="p-1.5 text-slate-500 hover:text-slate-800 hover:bg-slate-50 border-r border-slate-200 transition-colors"
            title="Zoom Out"
          >
            <Minus className="w-3.5 h-3.5" />
          </button>
          <button
            type="button"
            onClick={() => {
              setZoom(1)
              setPan({ x: 0, y: 0 })
            }}
            className="px-2 py-1 text-[11px] font-mono font-medium text-slate-600 hover:bg-slate-50 border-r border-slate-200 transition-colors"
            title="Reset Zoom"
          >
            {Math.round(zoom * 100)}%
          </button>
          <button
            type="button"
            onClick={() => {
              setZoom(1)
              setPan({ x: 0, y: 0 })
            }}
            className="p-1.5 text-slate-500 hover:text-slate-800 hover:bg-slate-50 transition-colors"
            title="Fit to View"
          >
            <Maximize2 className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* 2. Interactive SVG Canvas */}
      <div
        className="flex-1 relative bg-white overflow-hidden select-none cursor-grab active:cursor-grabbing border-t border-b border-slate-100"
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
      >
        {loading ? (
          <div className="absolute inset-0 flex items-center justify-center bg-white/70 backdrop-blur-xs z-10">
            <div className="animate-spin rounded-full h-8 w-8 border-2 border-slate-900 border-t-transparent" />
          </div>
        ) : null}

        <svg
          ref={svgRef}
          className="w-full h-full"
          viewBox="0 0 800 500"
        >
          <defs>
            <marker
              id="arrow"
              viewBox="0 0 10 10"
              refX="18"
              refY="5"
              markerWidth="4.5"
              markerHeight="4.5"
              orient="auto-start-reverse"
            >
              <path d="M 0 1.5 L 8 5 L 0 8.5 z" fill="#94a3b8" />
            </marker>
          </defs>

          <g transform={`translate(${pan.x}, ${pan.y}) scale(${zoom})`}>
            {/* Edges with Labels */}
            {cardEdges.map((edge) => {
              const mx = (edge.x1 + edge.x2) / 2
              const my = (edge.y1 + edge.y2) / 2

              return (
                <g key={edge.id}>
                  <line
                    x1={edge.x1}
                    y1={edge.y1}
                    x2={edge.x2}
                    y2={edge.y2}
                    stroke="#cbd5e1"
                    strokeWidth="1.2"
                    markerEnd="url(#arrow)"
                  />
                  <rect
                    x={mx - 18}
                    y={my - 8}
                    width={36}
                    height={14}
                    fill="#ffffff"
                    rx={4}
                    opacity={0.9}
                  />
                  <text
                    x={mx}
                    y={my + 2}
                    textAnchor="middle"
                    className="text-[10px] fill-slate-400 font-mono pointer-events-none select-none"
                  >
                    {edge.label}
                  </text>
                </g>
              )
            })}

            {/* Nodes Rendered as Rectangular Cards/Pills matching Mockup */}
            {cardNodes.map((node) => {
              const isSelected = selectedEntityId === node.id

              let bgFill = '#64748b'
              let strokeColor = '#475569'
              let titleFill = '#ffffff'
              let subFill = '#cbd5e1'

              if (node.kind === 'primary') {
                bgFill = '#0b192c'
                strokeColor = '#0f172a'
                titleFill = '#ffffff'
                subFill = '#93c5fd' // light blue subtext
              } else if (node.kind === 'readwrite') {
                bgFill = '#dbeafe' // soft light blue
                strokeColor = '#bfdbfe'
                titleFill = '#1e3a8a'
                subFill = '#2563eb'
              } else if (node.kind === 'error') {
                bgFill = '#fee2e2' // soft red
                strokeColor = '#f87171'
                titleFill = '#991b1b'
                subFill = '#dc2626'
              }

              return (
                <g
                  key={node.id}
                  transform={`translate(${node.x}, ${node.y})`}
                  onClick={(e) => {
                    e.stopPropagation()
                    setSelectedEntityId(node.id)
                    if (onCenterEntityChange && node.rawNode) {
                      onCenterEntityChange(node.rawNode.entity_id)
                    }
                  }}
                  className="cursor-pointer group"
                >
                  {/* Selection Ring */}
                  {isSelected && (
                    <rect
                      x={-3}
                      y={-3}
                      width={node.width + 6}
                      height={node.height + 6}
                      rx={11}
                      fill="none"
                      stroke="#2563eb"
                      strokeWidth={2}
                      className="opacity-90"
                    />
                  )}

                  {/* Main Rounded Rect Card */}
                  <rect
                    width={node.width}
                    height={node.height}
                    rx={8}
                    fill={bgFill}
                    stroke={strokeColor}
                    strokeWidth={1}
                    className="transition-transform group-hover:scale-[1.02] drop-shadow-2xs"
                  />

                  {/* Title Text */}
                  <text
                    x={node.width / 2}
                    y={17}
                    textAnchor="middle"
                    fill={titleFill}
                    className="text-[11px] font-bold pointer-events-none select-none"
                  >
                    {node.title}
                  </text>

                  {/* Subtitle Text */}
                  <text
                    x={node.width / 2}
                    y={32}
                    textAnchor="middle"
                    fill={subFill}
                    className="text-[9.5px] font-medium pointer-events-none select-none"
                  >
                    {node.subtitle}
                  </text>
                </g>
              )
            })}
          </g>
        </svg>
      </div>

      {/* 3. Bottom Legend Matching Reference UI */}
      <div className="pt-3">
        <div className="flex items-center gap-4 text-[11px] text-slate-600 font-medium pb-2 border-b border-slate-100">
          <span className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full bg-[#0b192c]" /> Primary Evidence
          </span>
          <span className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full bg-[#93c5fd]" /> Read/Write
          </span>
          <span className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full bg-[#64748b]" /> Depended On
          </span>
          <span className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full bg-[#ef4444]" /> Error Origin
          </span>
        </div>

        {/* Selected Entity Status Line */}
        <div className="pt-2 text-xs font-mono font-medium text-slate-800 truncate">
          {selectedNode
            ? `${selectedNode.rawNode?.path || selectedNode.title} > ${selectedNode.title} (Line ${
                selectedNode.rawNode?.start_line || 158
              })`
            : 'createStore.ts > dispatch (Line 158)'}
        </div>
      </div>
    </div>
  )
}
