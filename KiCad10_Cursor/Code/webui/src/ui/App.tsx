import React, { useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

type RunAction = "generate" | "check" | "review" | "repair" | "validate";
type RunTarget = "kicad" | "tscircuit" | "both";
type PlaceMode = "deterministic" | "llm";

type ProjectList = { projects: string[] };
type RunResponse = {
  command: string[];
  cwd: string;
  exit_code: number;
  stdout: string;
  stderr: string;
};

type ChatStartResponse = {
  session_id: string;
  assistant: string;
  captured: string[];
  json_path: string | null;
};

async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return (await res.json()) as T;
}

async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const text = await res.text();
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}\n${text}`);
  return JSON.parse(text) as T;
}

function Button(props: React.ButtonHTMLAttributes<HTMLButtonElement> & { tone?: "primary" | "danger" | "ghost" }) {
  const tone = props.tone ?? "primary";
  const style: React.CSSProperties = useMemo(() => {
    const base: React.CSSProperties = {
      borderRadius: 12,
      padding: "10px 12px",
      border: "1px solid var(--border)",
      background: "var(--panel)",
      color: "var(--text)",
      cursor: props.disabled ? "not-allowed" : "pointer",
      opacity: props.disabled ? 0.6 : 1,
      fontWeight: 600,
    };
    if (tone === "primary") return { ...base, background: "linear-gradient(180deg, rgba(94,234,212,0.18), rgba(94,234,212,0.08))" };
    if (tone === "danger") return { ...base, background: "linear-gradient(180deg, rgba(251,113,133,0.18), rgba(251,113,133,0.08))" };
    return { ...base, background: "transparent" };
  }, [props.disabled, tone]);

  return <button {...props} style={{ ...style, ...props.style }} />;
}

function Panel(props: { title: string; children: React.ReactNode; right?: React.ReactNode }) {
  return (
    <div style={{ border: "1px solid var(--border)", background: "var(--panel)", borderRadius: 16, padding: 14 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, marginBottom: 10 }}>
        <div style={{ fontWeight: 700 }}>{props.title}</div>
        {props.right}
      </div>
      {props.children}
    </div>
  );
}

export function App() {
  const [projects, setProjects] = useState<string[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [target, setTarget] = useState<RunTarget>("both");
  const [placeMode, setPlaceMode] = useState<PlaceMode>("deterministic");
  const [busy, setBusy] = useState(false);
  const [last, setLast] = useState<RunResponse | null>(null);
  const [error, setError] = useState<string>("");
  const [apiOnline, setApiOnline] = useState<boolean>(true);
  const [chatSession, setChatSession] = useState<string>("");
  const [chatInput, setChatInput] = useState("");
  const [chatInputRows, setChatInputRows] = useState(1);
  const [chatBusy, setChatBusy] = useState(false);
  const [chatMessages, setChatMessages] = useState<Array<{ role: "user" | "assistant"; text: string }>>([]);
  const [sideOpen, setSideOpen] = useState<{ project: boolean; actions: boolean }>({ project: true, actions: true });
  const [showProcessTrace, setShowProcessTrace] = useState(false);
  const [processTrace, setProcessTrace] = useState<string[]>([]);
  const [loadingDots, setLoadingDots] = useState(".");
  const [projectHint, setProjectHint] = useState<string>("");

  function pushTrace(msg: string) {
    const ts = new Date().toLocaleTimeString();
    setProcessTrace((prev) => [...prev.slice(-120), `[${ts}] ${msg}`]);
  }

  useEffect(() => {
    (async () => {
      try {
        await apiGet("/api/health");
        setApiOnline(true);
        const list = await apiGet<ProjectList>("/api/projects");
        setProjects(list.projects);
        setSelected((prev) => prev || list.projects[0] || "");
      } catch (e) {
        setApiOnline(false);
        setError(String(e));
      }
    })();
  }, []);

  useEffect(() => {
    if (!(busy || chatBusy)) {
      setLoadingDots(".");
      return;
    }
    const id = window.setInterval(() => {
      setLoadingDots((d) => (d.length >= 3 ? "." : d + "."));
    }, 350);
    return () => window.clearInterval(id);
  }, [busy, chatBusy]);

  async function refreshProjects(preferPath?: string) {
    try {
      const list = await apiGet<ProjectList>("/api/projects");
      let next = list.projects;
      if (preferPath && !next.includes(preferPath)) {
        next = [...next, preferPath].sort();
      }
      setProjects(next);
      if (preferPath) {
        setSelected(preferPath);
      }
    } catch (e) {
      pushTrace(`refresh projects: ${String(e)}`);
    }
  }

  const canRun = !!selected && !busy;

  /** Pass `jsonPath` when React `selected` may be stale (e.g. immediately after Save from chat). */
  async function run(action: RunAction, jsonPath?: string) {
    const path = jsonPath ?? selected;
    if (!path) {
      setError("No JSON selected. Pick one in Project panel or click Save JSON first.");
      pushTrace(`blocked ${action}: no json selected`);
      return;
    }
    setBusy(true);
    setError("");
    setLast(null);
    pushTrace(`start ${action} (${path})`);
    try {
      const payload =
        action === "generate"
          ? { action, json_path: path, target, placement: placeMode }
          : { action, json_path: path };
      const res = await apiPost<RunResponse>("/api/run", payload);
      setLast(res);
      pushTrace(`finish ${action}: exit ${res.exit_code}`);
    } catch (e) {
      setError(String(e));
      pushTrace(`error ${action}: ${String(e)}`);
    } finally {
      setBusy(false);
    }
  }

  async function startChat() {
    setChatBusy(true);
    setError("");
    pushTrace("start chat session");
    try {
      const res = await apiPost<ChatStartResponse>("/api/chat/start", { json_path: selected || null });
      setChatSession(res.session_id);
      setChatMessages([{ role: "assistant", text: res.assistant }]);
      if (res.json_path) setSelected(res.json_path);
    } catch (e) {
      setError(String(e));
      pushTrace(`chat start error: ${String(e)}`);
    } finally {
      setChatBusy(false);
    }
  }

  async function newSchematic() {
    // Fresh session with no json_path (new design).
    setSelected("");
    setChatSession("");
    setChatMessages([]);
    setChatInput("");
    setChatInputRows(1);
    setProjectHint(
      "New chat started. **Save JSON** writes to `Code/data/llm_output_<ProjectName>.json` (from your design’s `project_name`). " +
        "The Project dropdown refreshes after save — pick that file before using the side-panel buttons, or type chat commands after saving once."
    );
    await (async () => {
      setChatBusy(true);
      setError("");
      try {
        const res = await apiPost<ChatStartResponse>("/api/chat/start", { json_path: null });
        setChatSession(res.session_id);
        setChatMessages([{ role: "assistant", text: res.assistant }]);
        await refreshProjects();
      } catch (e) {
        setError(String(e));
      } finally {
        setChatBusy(false);
      }
    })();
  }

  async function sendChat() {
    if (!chatSession || !chatInput.trim()) return;
    const msg = chatInput.trim();
    setChatInput("");
    setChatInputRows(1);
    setChatMessages((m) => [...m, { role: "user", text: msg }]);

    const normalized = msg.toLowerCase().trim();
    // Match **gen** / **done** / **build** at line start (same as prompt_playground).
    const match =
      normalized.match(/^\/?(gen|generate|build|done|check|review|repair|validate)\b/) ??
      (/^(?:ok|yes|yeah|yep|sure|alright)[,!\s]+done\.?$/.test(normalized) ? (["", "done"] as const) : null);
    if (match) {
      const cmd = match[1] as "gen" | "generate" | "build" | "done" | "check" | "review" | "repair" | "validate";
      pushTrace(`chat command detected: ${cmd}`);
      // Always persist chat state before running — the dropdown may still point at an older file.
      const savedPath = await saveChat();
      const effectivePath = savedPath ?? selected;
      if (!effectivePath) {
        setChatMessages((m) => [
          ...m,
          {
            role: "assistant",
            text: "I couldn't run that command because saving failed or there is no JSON path. Click **Save JSON** once, then retry.",
          },
        ]);
        return;
      }
      if (savedPath) {
        pushTrace(`using saved json: ${savedPath}`);
      }
      const action: RunAction =
        cmd === "gen" || cmd === "generate" || cmd === "build" || cmd === "done" ? "generate" : (cmd as RunAction);
      const slowHint =
        action === "generate" && placeMode === "llm"
          ? " (this often takes **1–3 minutes**: Gemini placement + repair if needed + KiCad/tscircuit)."
          : action === "generate"
            ? " (typically **~10–30s** for both targets; longer if symbol repair runs)."
            : "";
      setChatMessages((m) => [
        ...m,
        {
          role: "assistant",
          text: `Running **${action}**${action === "generate" ? ` (${target}, ${placeMode})` : ""}.${slowHint}`,
        },
      ]);
      await run(action, effectivePath);
      return;
    }

    setChatBusy(true);
    pushTrace("chat send");
    try {
      const res = await apiPost<{ assistant: string }>("/api/chat/send", { session_id: chatSession, message: msg });
      setChatMessages((m) => [...m, { role: "assistant", text: res.assistant }]);
      pushTrace("chat response received");
    } catch (e) {
      setError(String(e));
      pushTrace(`chat send error: ${String(e)}`);
    } finally {
      setChatBusy(false);
    }
  }

  async function saveChat(): Promise<string | null> {
    if (!chatSession) return null;
    setChatBusy(true);
    try {
      const res = await apiPost<{ json_path: string }>("/api/chat/save", { session_id: chatSession });
      setSelected(res.json_path);
      await refreshProjects(res.json_path);
      pushTrace(`saved chat json: ${res.json_path}`);
      return res.json_path;
    } catch (e) {
      setError(String(e));
      pushTrace(`save chat error: ${String(e)}`);
    } finally {
      setChatBusy(false);
    }
    return null;
  }

  return (
    <div style={{ maxWidth: 1400, margin: "0 auto", padding: "20px 16px 34px" }}>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 16, marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: 22, fontWeight: 800, letterSpacing: 0.2 }}>SchematIQ</div>
          <div style={{ color: "var(--muted)", marginTop: 6 }}>
            Pick an LLM project JSON, then run <b>Generate</b> or <b>Check</b>.
          </div>
        </div>
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <span style={{ color: "var(--muted)", fontSize: 13 }}>API</span>
          <span style={{ padding: "6px 10px", borderRadius: 999, border: "1px solid var(--border)", background: "var(--panel)" }}>
            <span style={{ color: apiOnline ? "var(--accent)" : "var(--danger)", fontWeight: 700 }}>
              {apiOnline ? "localhost" : "offline"}
            </span>
          </span>
          {(busy || chatBusy) ? (
            <span style={{ color: "var(--warn)", fontWeight: 700, fontSize: 13 }}>loading{loadingDots}</span>
          ) : null}
        </div>
      </div>

      <div style={{ marginTop: 12, display: "grid", gridTemplateColumns: "2.2fr 1fr", gap: 12, alignItems: "start" }}>
        <Panel
          title="Chatbot"
          right={
            <div style={{ display: "flex", gap: 8 }}>
              <Button tone="ghost" disabled={chatBusy || !chatSession} onClick={saveChat}>
                Save JSON
              </Button>
              <Button disabled={chatBusy} onClick={startChat}>
                {chatSession ? "New chat" : "Start chat"}
              </Button>
            </div>
          }
        >
          <div style={{ display: "grid", gap: 10 }}>
            <div
              style={{
                border: "1px solid var(--border)",
                borderRadius: 12,
                background: "rgba(255,255,255,0.03)",
                minHeight: 320,
                maxHeight: "70vh",
                overflow: "auto",
                padding: 10,
                display: "grid",
                gap: 8,
              }}
            >
              {chatMessages.length === 0 ? (
                <div style={{ color: "var(--muted)" }}>Start chat to use the website like `prompt_playground.py`.</div>
              ) : (
                chatMessages.map((m, i) => (
                  <div
                    key={i}
                    style={{
                      padding: 10,
                      borderRadius: 10,
                      border: "1px solid var(--border)",
                      background: m.role === "assistant" ? "rgba(94,234,212,0.06)" : "rgba(255,255,255,0.04)",
                    }}
                  >
                    <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 6 }}>{m.role}</div>
                    {m.role === "assistant" ? (
                      <div style={{ fontSize: 14, lineHeight: 1.5 }}>
                        <ReactMarkdown
                          remarkPlugins={[remarkGfm]}
                          components={{
                            code(props) {
                              const { className, children, ...rest } = props;
                              const isBlock = (className || "").includes("language-") || String(children).includes("\n");
                              if (!isBlock) {
                                return (
                                  <code
                                    {...rest}
                                    style={{
                                      background: "rgba(255,255,255,0.08)",
                                      border: "1px solid var(--border)",
                                      borderRadius: 6,
                                      padding: "1px 5px",
                                      fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
                                    }}
                                  >
                                    {children}
                                  </code>
                                );
                              }
                              return (
                                <pre
                                  style={{
                                    margin: "8px 0",
                                    padding: 10,
                                    background: "rgba(0,0,0,0.25)",
                                    border: "1px solid var(--border)",
                                    borderRadius: 10,
                                    overflowX: "auto",
                                  }}
                                >
                                  <code {...rest} className={className}>
                                    {children}
                                  </code>
                                </pre>
                              );
                            },
                          }}
                        >
                          {m.text}
                        </ReactMarkdown>
                      </div>
                    ) : (
                      <pre style={{ margin: 0, whiteSpace: "pre-wrap", fontFamily: "inherit" }}>{m.text}</pre>
                    )}
                  </div>
                ))
              )}
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <textarea
                value={chatInput}
                rows={chatInputRows}
                onChange={(e) => {
                  const v = e.target.value;
                  setChatInput(v);
                  const rows = Math.min(8, Math.max(1, v.split("\n").length));
                  setChatInputRows(rows);
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    void sendChat();
                  }
                }}
                disabled={!chatSession || chatBusy}
                placeholder={chatSession ? "Message SchematIQ..." : "Start chat first"}
                style={{
                  flex: 1,
                  borderRadius: 10,
                  border: "1px solid var(--border)",
                  background: "rgba(255,255,255,0.04)",
                  color: "var(--text)",
                  padding: "10px 12px",
                  resize: "none",
                  lineHeight: 1.35,
                }}
              />
              <Button disabled={!chatSession || chatBusy || !chatInput.trim()} onClick={sendChat}>
                Send
              </Button>
            </div>
            <div style={{ color: "var(--muted)", fontSize: 12 }}>
              Chat shortcuts: <code>gen</code>, <code>done</code>, <code>build</code>, <code>check</code>, <code>review</code>,{" "}
              <code>repair</code>, <code>validate</code>
            </div>
          </div>
        </Panel>
        <div style={{ display: "grid", gap: 12 }}>
          <Panel
            title="Project"
            right={
              <div style={{ display: "flex", gap: 8 }}>
                <Button tone="ghost" disabled={!apiOnline || busy || chatBusy} onClick={newSchematic}>
                  New
                </Button>
                <Button tone="ghost" disabled={busy} onClick={() => window.location.reload()}>
                  Refresh
                </Button>
                <Button
                  tone="ghost"
                  disabled={busy}
                  onClick={() => setSideOpen((s) => ({ ...s, project: !s.project }))}
                  title="Collapse"
                >
                  {sideOpen.project ? "Hide" : "Show"}
                </Button>
              </div>
            }
          >
            {sideOpen.project ? (
              <div style={{ display: "grid", gap: 10 }}>
                {projectHint ? (
                  <div
                    style={{
                      fontSize: 12,
                      lineHeight: 1.45,
                      color: "var(--text)",
                      border: "1px solid var(--border)",
                      borderRadius: 10,
                      padding: "10px 12px",
                      background: "rgba(94,234,212,0.06)",
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", gap: 8, marginBottom: 6 }}>
                      <span style={{ fontWeight: 700 }}>New project</span>
                      <button
                        type="button"
                        onClick={() => setProjectHint("")}
                        style={{
                          border: "none",
                          background: "transparent",
                          color: "var(--muted)",
                          cursor: "pointer",
                          fontSize: 12,
                          textDecoration: "underline",
                        }}
                      >
                        Dismiss
                      </button>
                    </div>
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{projectHint}</ReactMarkdown>
                  </div>
                ) : null}
                <label style={{ display: "grid", gap: 6 }}>
                  <div style={{ color: "var(--muted)", fontSize: 13 }}>LLM output JSON</div>
                  <select
                    value={selected}
                    onChange={(e) => setSelected(e.target.value)}
                    style={{
                      width: "100%",
                      borderRadius: 12,
                      padding: "10px 12px",
                      border: "1px solid var(--border)",
                      background: "rgba(255,255,255,0.04)",
                      color: "var(--text)",
                    }}
                  >
                    {projects.length === 0 ? <option value="">(none found)</option> : null}
                    {projects.map((p) => (
                      <option key={p} value={p}>
                        {p}
                      </option>
                    ))}
                  </select>
                </label>

                <label style={{ display: "grid", gap: 6 }}>
                  <div style={{ color: "var(--muted)", fontSize: 13 }}>Generate target</div>
                  <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                    {(["both", "kicad", "tscircuit"] as const).map((t) => (
                      <Button
                        key={t}
                        tone={target === t ? "primary" : "ghost"}
                        disabled={!apiOnline || busy}
                        onClick={() => setTarget(t)}
                        style={{ padding: "8px 10px" }}
                      >
                        {t}
                      </Button>
                    ))}
                  </div>
                </label>
              </div>
            ) : (
              <div style={{ color: "var(--muted)", fontSize: 13 }}>Collapsed</div>
            )}
          </Panel>

          <Panel title="Actions">
            <div style={{ display: "grid", gap: 10 }}>
              <div style={{ display: "flex", gap: 8 }}>
                <Button
                  tone="ghost"
                  disabled={busy}
                  onClick={() => setSideOpen((s) => ({ ...s, actions: !s.actions }))}
                >
                  {sideOpen.actions ? "Hide" : "Show"}
                </Button>
              </div>
              {sideOpen.actions ? (
                <>
                  <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                    <Button disabled={!apiOnline || !canRun} onClick={() => run("generate")}>
                      {busy ? "Running…" : "Generate"}
                    </Button>
                    <Button disabled={!apiOnline || !canRun} onClick={() => run("check")}>
                      Check
                    </Button>
                    <Button disabled={!apiOnline || !canRun} tone="ghost" onClick={() => run("review")}>
                      Review only
                    </Button>
                    <Button disabled={!apiOnline || !canRun} tone="ghost" onClick={() => run("validate")}>
                      Validate symbols
                    </Button>
                    <Button disabled={!apiOnline || !canRun} tone="danger" onClick={() => run("repair")}>
                      Repair symbols
                    </Button>
                  </div>
                  <div style={{ display: "grid", gap: 6 }}>
                    <div style={{ color: "var(--muted)", fontSize: 13 }}>Placement</div>
                    <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                      {(["deterministic", "llm"] as const).map((m) => (
                        <Button
                          key={m}
                          tone={placeMode === m ? "primary" : "ghost"}
                          disabled={!apiOnline || busy}
                          onClick={() => setPlaceMode(m)}
                          style={{ padding: "8px 10px" }}
                        >
                          {m === "deterministic" ? "Deterministic" : "LLM place (minimal)"}
                        </Button>
                      ))}
                    </div>
                    <div style={{ color: "var(--muted)", fontSize: 12, lineHeight: 1.35 }}>
                      LLM mode only changes symbol positions. Nets/wires/labels are still generated deterministically.
                      A placement report is written under <code>reports/*_placement.json</code>. Expect roughly{" "}
                      <b>20–60s extra</b> for the placement Gemini call (plus repair LLM if symbols are unresolved) — the
                      API waits for the full subprocess, so the UI stays on “loading” until it finishes. Use{" "}
                      <b>Show trace</b> in Logs to confirm the server started the command.
                    </div>
                  </div>
                  <div style={{ color: "var(--muted)", fontSize: 13, lineHeight: 1.35 }}>
                    <b>Check</b> runs symbol validation + electrical review (and generates KiCad so you can open it). Full JSON reports land in{" "}
                    <code style={{ color: "var(--text)" }}>Code/reports/</code>.
                  </div>
                </>
              ) : (
                <div style={{ color: "var(--muted)", fontSize: 13 }}>Collapsed</div>
              )}
            </div>
          </Panel>

          <Panel
            title="Logs"
            right={
              <Button tone="ghost" onClick={() => setShowProcessTrace((s) => !s)}>
                {showProcessTrace ? "Hide trace" : "Show trace"}
              </Button>
            }
          >
          {showProcessTrace ? (
            <div
              style={{
                maxHeight: 180,
                overflow: "auto",
                border: "1px solid var(--border)",
                borderRadius: 10,
                background: "rgba(255,255,255,0.02)",
                padding: 8,
                marginBottom: 10,
              }}
            >
              <pre style={{ margin: 0, whiteSpace: "pre-wrap", color: "var(--muted)", fontSize: 12 }}>
                {processTrace.length ? processTrace.join("\n") : "No subprocesses/actions yet."}
              </pre>
            </div>
          ) : null}
          {error ? (
            <pre style={{ margin: 0, whiteSpace: "pre-wrap", color: "var(--danger)" }}>{error}</pre>
          ) : last ? (
            <div style={{ display: "grid", gap: 10 }}>
              <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
                <span
                  style={{
                    padding: "6px 10px",
                    borderRadius: 999,
                    border: "1px solid var(--border)",
                    background: last.exit_code === 0 ? "rgba(94,234,212,0.10)" : "rgba(251,113,133,0.10)",
                    color: last.exit_code === 0 ? "var(--accent)" : "var(--danger)",
                    fontWeight: 800,
                  }}
                >
                  exit {last.exit_code}
                </span>
                <span style={{ color: "var(--muted)", fontSize: 13 }}>
                  <b>cwd</b> {last.cwd}
                </span>
              </div>
              <div style={{ color: "var(--muted)", fontSize: 13 }}>
                <b>command</b> <code style={{ color: "var(--text)" }}>{last.command.join(" ")}</code>
              </div>
              {last.stderr ? (
                <div style={{ border: "1px solid rgba(251,113,133,0.25)", background: "rgba(251,113,133,0.06)", borderRadius: 12, padding: 10 }}>
                  <div style={{ color: "var(--danger)", fontWeight: 800, marginBottom: 6 }}>stderr</div>
                  <pre style={{ margin: 0, whiteSpace: "pre-wrap", color: "var(--text)" }}>{last.stderr}</pre>
                </div>
              ) : null}
              <div style={{ border: "1px solid var(--border)", background: "rgba(255,255,255,0.03)", borderRadius: 12, padding: 10 }}>
                <div style={{ color: "var(--muted)", fontWeight: 800, marginBottom: 6 }}>stdout</div>
                <pre style={{ margin: 0, whiteSpace: "pre-wrap", color: "var(--text)" }}>{last.stdout || "(no output)"}</pre>
              </div>
            </div>
          ) : (
            <div style={{ color: "var(--muted)" }}>Run an action to see output here.</div>
          )}
          </Panel>
        </div>
      </div>
    </div>
  );
}

