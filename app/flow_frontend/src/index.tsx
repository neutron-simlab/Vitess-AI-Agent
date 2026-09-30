import { useEffect, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import {
  Background,
  Controls,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type NodeProps,
  type Node,
} from "@xyflow/react";
import type { FrontendRendererArgs } from "@streamlit/component-v2-lib";
import "@xyflow/react/dist/style.css";
import "./style.css";

type Module = {
  name: string;
  label: string;
  required: boolean;
  hint: string;
  description: string;
};
type Issue = { modules: string[]; message: string; correction: string };
type Preset = {
  id: string;
  label: string;
  description: string;
  defaults: string[];
  required: string[];
};
type Draft = { preset: string; modules: string[] };
type Data = {
  manifest: { modules: Omit<Module, "required">[]; presets: Preset[] };
  preset: string;
  modules: string[];
  issues: Issue[];
  revision: number | null;
  feedback: string | null;
  locked: boolean;
};
type Block = Node<
  {
    module: Module;
    error: boolean;
    editable: boolean;
    remove: (name: string) => void;
  },
  "module"
>;

function ModuleBlock({ data }: NodeProps<Block>) {
  return (
    <div
      className={`module-block ${data.error ? "invalid" : ""}`}
      title={data.module.hint}
    >
      <Handle type="target" position={Position.Left} />
      <span className="module-kind">
        {data.module.required ? "Required" : "Optional"}
      </span>
      <strong>{data.module.label}</strong>
      {!data.module.required && data.editable && (
        <button
          className="nodrag remove"
          aria-label={`Remove ${data.module.label}`}
          onClick={() => data.remove(data.module.name)}
        >
          ×
        </button>
      )}
      <Handle type="source" position={Position.Right} />
    </div>
  );
}
const nodeTypes = { module: ModuleBlock };
const STEP = 225;

function Canvas({
  data,
  publish,
  confirm,
}: {
  data: Data;
  publish: (draft: Draft) => void;
  confirm: (draft: Draft) => void;
}) {
  const [draft, setDraft] = useState<Draft>({
    preset: data.preset,
    modules: data.modules,
  });
  const { modules } = draft;
  const preset = data.manifest.presets.find(
    (item) => item.id === draft.preset,
  )!;
  const [dragging, setDragging] = useState<string | null>(null);
  const [hint, setHint] = useState(
    "Drag an optional module to its highlighted position.",
  );
  const [submitting, setSubmitting] = useState(false);
  const editingDisabled = data.locked || submitting;
  useEffect(
    () => setDraft({ preset: data.preset, modules: data.modules }),
    [data.preset, data.modules.join("|")],
  );
  useEffect(() => setSubmitting(false), [data.feedback]);
  const flow = useReactFlow();
  const catalog = data.manifest.modules.map((module) => ({
    ...module,
    required: preset.required.includes(module.name),
  }));
  const selected = catalog.filter((item) => modules.includes(item.name));
  const palette = catalog.filter((item) => !item.required);
  const indexFor = (name: string) => {
    const rank = catalog.findIndex((item) => item.name === name);
    return selected.filter((item) => catalog.indexOf(item) < rank).length;
  };
  const update = (next: string[]) => {
    if (editingDisabled) return;
    const nextDraft = { preset: draft.preset, modules: next };
    setDraft(nextDraft);
    publish(nextDraft);
  };
  const choosePreset = (id: string) => {
    if (editingDisabled) return;
    const selectedPreset = data.manifest.presets.find(
      (item) => item.id === id,
    )!;
    const nextDraft = { preset: id, modules: selectedPreset.defaults };
    setDraft(nextDraft);
    publish(nextDraft);
    setDragging(null);
    setHint("Drag an optional module to its highlighted position.");
  };
  const insert = (name: string) => {
    if (editingDisabled || modules.includes(name)) return;
    const next = [...modules];
    next.splice(indexFor(name), 0, name);
    update(next);
    setDragging(null);
  };
  const nodes: Block[] = selected.map((module, index) => ({
    id: module.name,
    type: "module",
    position: { x: index * STEP, y: 85 },
    data: {
      module,
      error: data.issues.some((issue) => issue.modules.includes(module.name)),
      editable: !editingDisabled,
      remove: (name) => {
        update(modules.filter((item) => item !== name));
      },
    },
    draggable: false,
  }));
  const edges = selected.slice(1).map((item, index) => ({
    id: `${selected[index].name}-${item.name}`,
    source: selected[index].name,
    target: item.name,
    markerEnd: {
      type: MarkerType.ArrowClosed,
      color: "#477985",
      width: 20,
      height: 20,
    },
    type: "smoothstep",
    style: { stroke: "#477985", strokeWidth: 2 },
  }));
  const slot = dragging && !editingDisabled ? indexFor(dragging) : -1;
  const slotNode: Node[] =
    slot < 0
      ? []
      : [
          {
            id: "insertion-slot",
            position: { x: slot * STEP - 40, y: 50 },
            data: { label: "+" },
            style: {
              width: 40,
              height: 150,
              border: "2px dashed #2c8190",
              background: "#dceff0",
              color: "#18535b",
              fontSize: 26,
            },
            draggable: false,
            selectable: false,
          },
        ];
  useEffect(() => {
    const timer = setTimeout(
      () => void flow.fitView({ padding: 0.08, maxZoom: 1 }),
      40,
    );
    return () => clearTimeout(timer);
  }, [modules.join("|"), dragging]);
  const drop = (event: React.DragEvent) => {
    event.preventDefault();
    if (editingDisabled) return;
    const name = event.dataTransfer.getData("application/vitess-module");
    if (!dragging || name !== dragging) return;
    const point = flow.screenToFlowPosition({
      x: event.clientX,
      y: event.clientY,
    });
    const target = indexFor(name) * STEP - 20;
    if (Math.abs(point.x - target) <= 85 && point.y >= 15 && point.y <= 235)
      insert(name);
    else {
      setDragging(null);
      setHint("Drop on the highlighted insertion slot.");
    }
  };
  return (
    <section className="flow-builder" aria-label="Pipeline builder">
      <div className="builder-heading">
        <div>
          <h3>{data.locked ? "Confirmed pipeline" : "Build your pipeline"}</h3>
          <p>
            {data.locked
              ? `${preset.label} · The sequence is locked. Configure its modules in the chat below.`
              : "Choose the modules first. Configure their parameters with the specialists next."}
          </p>
        </div>
        <span className="step">{data.locked ? "Locked" : "1 · Assemble"}</span>
      </div>
      {!data.locked && (
        <>
          <div className="preset-picker">
            <label htmlFor="pipeline-preset">Pipeline preset</label>
            <select
              id="pipeline-preset"
              value={draft.preset}
              disabled={editingDisabled}
              onChange={(event) => choosePreset(event.target.value)}
            >
              {data.manifest.presets.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label}
                </option>
              ))}
            </select>
            <p>
              {preset.description} Choosing a preset replaces the current draft.
            </p>
          </div>
          <div className="module-palette" aria-label="Optional modules">
            {palette.map((module) => (
              <button
                key={module.name}
                draggable={!editingDisabled && !modules.includes(module.name)}
                disabled={editingDisabled || modules.includes(module.name)}
                title={module.hint}
                onFocus={() => setHint(module.hint)}
                onMouseEnter={() => setHint(module.hint)}
                onDragStart={(event) => {
                  if (editingDisabled) {
                    event.preventDefault();
                    return;
                  }
                  event.dataTransfer.setData(
                    "application/vitess-module",
                    module.name,
                  );
                  event.dataTransfer.effectAllowed = "copy";
                  setDragging(module.name);
                  setHint(module.hint);
                }}
                onDragEnd={() => setDragging(null)}
                onClick={() => insert(module.name)}
              >
                <span>{modules.includes(module.name) ? "✓" : "+"}</span>{" "}
                {module.label}
              </button>
            ))}
          </div>
          <p className="placement-hint" role="status">
            {hint}
          </p>
        </>
      )}
      <div
        className="flow-canvas"
        onDragOver={(event) => {
          if (editingDisabled) return;
          event.preventDefault();
          event.dataTransfer.dropEffect = "copy";
        }}
        onDrop={drop}
      >
        <ReactFlow
          nodes={[...nodes, ...slotNode]}
          edges={edges}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.08, maxZoom: 1 }}
          nodesConnectable={false}
          edgesReconnectable={false}
          deleteKeyCode={null}
          minZoom={0.3}
          maxZoom={1.5}
        >
          <Background gap={18} size={1} />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
      {data.issues.map((issue, index) => (
        <div role="alert" className="validation-error" key={index}>
          <strong>{issue.message}</strong> {issue.correction}
        </div>
      ))}
      <div className="builder-footer">
        <span>{modules.length} modules · One sequential pipeline</span>
        {!data.locked && (
          <button
            className="confirm"
            disabled={editingDisabled}
            onClick={() => {
              if (editingDisabled) return;
              setSubmitting(true);
              confirm(draft);
            }}
          >
            {submitting ? "Validating…" : "Confirm pipeline"}
          </button>
        )}
      </div>
    </section>
  );
}

const mounts = new WeakMap<object, { root: Root; host: HTMLDivElement }>();

export default function render({
  data,
  parentElement,
  setStateValue,
  setTriggerValue,
}: FrontendRendererArgs) {
  let mount = mounts.get(parentElement);
  if (!mount) {
    const host = document.createElement("div");
    parentElement.appendChild(host);
    mount = { root: createRoot(host), host };
    mounts.set(parentElement, mount);
  }
  const { root, host } = mount;
  root.render(
    <ReactFlowProvider>
      <Canvas
        key={(data as Data).revision}
        data={data as Data}
        publish={(draft) => setStateValue("draft", draft)}
        confirm={(draft) =>
          setTriggerValue("confirm", { id: crypto.randomUUID(), ...draft })
        }
      />
    </ReactFlowProvider>,
  );
  return () => {
    root.unmount();
    host.remove();
    mounts.delete(parentElement);
  };
}
