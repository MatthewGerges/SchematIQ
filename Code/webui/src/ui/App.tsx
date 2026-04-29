import React, { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

type RunAction = "generate" | "check" | "review" | "repair" | "validate";
type RunResponse = {
  command: string[];
  cwd: string;
  exit_code: number;
  stdout: string;
  stderr: string;
  kicad_pro_path?: string | null;
};

type ChatStartResponse = {
  session_id: string;
  assistant: string;
  captured: string[];
  json_path: string | null;
  state?: ProjectState;
};

type ChatSendResponse = {
  assistant: string;
  captured: string[];
  state: ProjectState;
};

type ProjectState = {
  project_name?: string;
  sheets?: unknown[];
  components?: unknown[];
  passives?: unknown[];
  nets?: unknown[];
};

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "").trim().replace(/\/+$/, "");

function apiUrl(path: string): string {
  if (/^https?:\/\//i.test(path)) return path;
  if (!path.startsWith("/")) {
    throw new Error(`API path must start with '/': ${path}`);
  }
  return API_BASE_URL ? `${API_BASE_URL}${path}` : path;
}

async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(apiUrl(path), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const text = await res.text();
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}\n${text}`);
  return JSON.parse(text) as T;
}

function isGenerateReady(state: ProjectState | null): boolean {
  if (!state) return false;
  const sheets = state.sheets?.length ?? 0;
  const comps = state.components?.length ?? 0;
  const nets = state.nets?.length ?? 0;
  return sheets > 0 && comps > 0 && nets > 0;
}

function extractKicadProjectPath(stdout: string, stderr: string): string | null {
  const combined = `${stdout}\n${stderr}`;
  const m = combined.match(/(\/[^\s'"]+\.kicad_pro)\b/);
  return m ? m[1] : null;
}

export function App() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>("");
  const [apiOnline, setApiOnline] = useState<boolean>(true);
  const [chatSession, setChatSession] = useState<string>("");
  const [chatInput, setChatInput] = useState("");
  const [chatBusy, setChatBusy] = useState(false);
  const [chatMessages, setChatMessages] = useState<Array<{ role: "user" | "assistant"; text: string }>>([]);
  const [stateSnapshot, setStateSnapshot] = useState<ProjectState | null>(null);
  const [lastJsonPath, setLastJsonPath] = useState<string>("");
  const [lastKicadProPath, setLastKicadProPath] = useState<string>("");
  const [loadingDots, setLoadingDots] = useState(".");
  const chatLogRef = useRef<HTMLDivElement | null>(null);
  const chatInputRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const health = await fetch(apiUrl("/api/health"));
        if (!health.ok) throw new Error(`${health.status} ${health.statusText}`);
        setApiOnline(true);
        await startChat();
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

  useEffect(() => {
    const el = chatLogRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [chatMessages, chatBusy]);

  useEffect(() => {
    const el = chatInputRef.current;
    if (!el) return;
    el.style.height = "0px";
    const next = Math.min(220, el.scrollHeight);
    el.style.height = `${next}px`;
    el.style.overflowY = el.scrollHeight > 220 ? "auto" : "hidden";
  }, [chatInput]);

  async function run(action: RunAction, jsonPath: string) {
    setBusy(true);
    setError("");
    try {
      const payload = action === "generate" ? { action, json_path: jsonPath, target: "kicad" } : { action, json_path: jsonPath };
      const res = await apiPost<RunResponse>("/api/run", payload);
      if (action === "generate") {
        const proPath = res.kicad_pro_path || extractKicadProjectPath(res.stdout || "", res.stderr || "");
        if (proPath) {
          setLastKicadProPath(proPath);
          setChatMessages((m) => [...m, { role: "assistant", text: `Saved KiCad project: \`${proPath}\`` }]);
        } else {
          setChatMessages((m) => [...m, { role: "assistant", text: "Generation finished, but I couldn't parse the `.kicad_pro` path from output." }]);
        }
      }
      if (res.exit_code !== 0) throw new Error(res.stderr || `Command failed with exit ${res.exit_code}`);
    } catch (e) {
      setError(String(e));
      setChatMessages((m) => [...m, { role: "assistant", text: `Command failed: ${String(e)}` }]);
    } finally {
      setBusy(false);
    }
  }

  async function startChat() {
    setChatBusy(true);
    setError("");
    try {
      const res = await apiPost<ChatStartResponse>("/api/chat/start", { json_path: null });
      setChatSession(res.session_id);
      setChatMessages([{ role: "assistant", text: res.assistant }]);
      setStateSnapshot(res.state ?? null);
      if (res.json_path) setLastJsonPath(res.json_path);
    } catch (e) {
      setError(String(e));
    } finally {
      setChatBusy(false);
    }
  }

  async function sendChat() {
    if (!chatSession || !chatInput.trim()) return;
    const msg = chatInput.trim();
    setChatInput("");
    setChatMessages((m) => [...m, { role: "user", text: msg }]);

    const normalized = msg.toLowerCase().trim();
    const match =
      normalized.match(/^\/?(gen|generate|build|done|check|review|repair|validate)\b/) ??
      (/^(?:ok|yes|yeah|yep|sure|alright)[,!\s]+done\.?$/.test(normalized) ? (["", "done"] as const) : null);
    if (match) {
      const cmd = match[1] as "gen" | "generate" | "build" | "done" | "check" | "review" | "repair" | "validate";

      if ((cmd === "gen" || cmd === "generate" || cmd === "build" || cmd === "done") && !isGenerateReady(stateSnapshot)) {
        setChatBusy(true);
        try {
          const guidance = await apiPost<ChatSendResponse>("/api/chat/send", {
            session_id: chatSession,
            message:
              "User typed gen/done before full design capture. If the design is not complete, explain exactly what step is still missing before generation. If complete enough, say so and provide only the missing confirmations.",
          });
          setChatMessages((m) => [...m, { role: "assistant", text: guidance.assistant }]);
          setStateSnapshot(guidance.state);
        } catch (e) {
          setError(String(e));
        } finally {
          setChatBusy(false);
        }
        return;
      }

      const savedPath = await saveChat();
      const effectivePath = savedPath ?? lastJsonPath;
      if (!effectivePath) {
        setChatMessages((m) => [
          ...m,
          {
            role: "assistant",
            text: "I couldn't run that command because there is no saved JSON path yet. Keep chatting and try again.",
          },
        ]);
        return;
      }
      const action: RunAction =
        cmd === "gen" || cmd === "generate" || cmd === "build" || cmd === "done" ? "generate" : (cmd as RunAction);
      setChatMessages((m) => [
        ...m,
        {
          role: "assistant",
          text: action === "generate" ? "Generating KiCad project..." : `Running **${action}**...`,
        },
      ]);
      await run(action, effectivePath);
      return;
    }

    setChatBusy(true);
    try {
      const res = await apiPost<ChatSendResponse>("/api/chat/send", { session_id: chatSession, message: msg });
      setChatMessages((m) => [...m, { role: "assistant", text: res.assistant }]);
      setStateSnapshot(res.state);
    } catch (e) {
      setError(String(e));
    } finally {
      setChatBusy(false);
    }
  }

  async function saveChat(): Promise<string | null> {
    if (!chatSession) return null;
    setChatBusy(true);
    try {
      const res = await apiPost<{ json_path: string }>("/api/chat/save", { session_id: chatSession });
      setLastJsonPath(res.json_path);
      return res.json_path;
    } catch (e) {
      setError(String(e));
    } finally {
      setChatBusy(false);
    }
    return null;
  }

  return (
    <div style={{ maxWidth: 1360, margin: "0 auto", padding: "20px 16px 34px" }}>
      <style>{`
        .schematiq-chat-scroll {
          scrollbar-width: thin;
          scrollbar-color: rgba(94,234,212,0.45) rgba(255,255,255,0.08);
        }
        .schematiq-chat-scroll::-webkit-scrollbar {
          width: 8px;
          height: 8px;
        }
        .schematiq-chat-scroll::-webkit-scrollbar-track {
          background: rgba(255,255,255,0.08);
          border-radius: 8px;
        }
        .schematiq-chat-scroll::-webkit-scrollbar-thumb {
          background: rgba(94,234,212,0.45);
          border-radius: 8px;
        }
        .schematiq-input-scroll {
          scrollbar-width: thin;
          scrollbar-color: rgba(94,234,212,0.45) rgba(255,255,255,0.08);
        }
        .schematiq-input-scroll::-webkit-scrollbar {
          width: 8px;
          height: 8px;
        }
        .schematiq-input-scroll::-webkit-scrollbar-track {
          background: rgba(255,255,255,0.08);
          border-radius: 8px;
        }
        .schematiq-input-scroll::-webkit-scrollbar-thumb {
          background: rgba(94,234,212,0.45);
          border-radius: 8px;
        }
      `}</style>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 16, marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: 22, fontWeight: 800, letterSpacing: 0.2 }}>SchematIQ</div>
          <div style={{ color: "var(--muted)", marginTop: 6 }}>Chat-only workflow: use <b>gen</b> or <b>done</b> in chat.</div>
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

      <div style={{ marginTop: 12, display: "grid", gap: 12, gridTemplateColumns: "1fr", width: "100%" }}>
        <div style={{ border: "1px solid var(--border)", background: "var(--panel)", borderRadius: 16, padding: 14 }}>
          <div style={{ fontWeight: 700, marginBottom: 10 }}>Chatbot</div>
          <div style={{ display: "grid", gap: 10 }}>
            <div
              ref={chatLogRef}
              className="schematiq-chat-scroll"
              style={{
                border: "1px solid var(--border)",
                borderRadius: 12,
                background: "rgba(255,255,255,0.03)",
                minHeight: 320,
                maxHeight: "62vh",
                overflowY: "auto",
                overflowX: "auto",
                overscrollBehavior: "contain",
                padding: 10,
                display: "grid",
                gap: 8,
                width: "100%",
              }}
            >
              {chatMessages.length === 0 ? <div style={{ color: "var(--muted)" }}>Initializing chat...</div> : chatMessages.map((m, i) => (
                <div key={i} style={{ padding: 10, borderRadius: 10, border: "1px solid var(--border)", background: m.role === "assistant" ? "rgba(94,234,212,0.06)" : "rgba(255,255,255,0.04)", minWidth: 0 }}>
                  <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 6 }}>{m.role}</div>
                  {m.role === "assistant" ? (
                    <div style={{ fontSize: 14, lineHeight: 1.5, overflowWrap: "anywhere", wordBreak: "break-word", minWidth: 0 }}>
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
                    <pre style={{ margin: 0, whiteSpace: "pre-wrap", overflowWrap: "anywhere", wordBreak: "break-word", fontFamily: "inherit" }}>{m.text}</pre>
                  )}
                </div>
              ))}
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <textarea
                ref={chatInputRef}
                className="schematiq-input-scroll"
                value={chatInput}
                onChange={(e) => {
                  setChatInput(e.target.value);
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    void sendChat();
                  }
                }}
                disabled={!chatSession || chatBusy || busy}
                placeholder={chatSession ? "Message SchematIQ..." : "Connecting to chat..."}
                style={{
                  flex: 1,
                  minHeight: 44,
                  maxHeight: 220,
                  borderRadius: 10,
                  border: "1px solid var(--border)",
                  background: "rgba(255,255,255,0.04)",
                  color: "var(--text)",
                  padding: "10px 12px",
                  resize: "none",
                  lineHeight: 1.35,
                }}
              />
              <button
                disabled={!chatSession || chatBusy || busy || !chatInput.trim()}
                onClick={sendChat}
                aria-label="Send message"
                title="Send"
                style={{
                  borderRadius: 12,
                  width: 44,
                  height: 44,
                  display: "inline-flex",
                  alignItems: "center",
                  justifyContent: "center",
                  border: "1px solid var(--border)",
                  background: "linear-gradient(180deg, rgba(94,234,212,0.18), rgba(94,234,212,0.08))",
                  color: "var(--text)",
                  cursor: !chatSession || chatBusy || busy || !chatInput.trim() ? "not-allowed" : "pointer",
                  opacity: !chatSession || chatBusy || busy || !chatInput.trim() ? 0.6 : 1,
                  fontWeight: 600,
                }}
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                  <path d="M3 11.5L20 4l-7.5 17-2.2-6.3L3 11.5Z" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
                </svg>
              </button>
            </div>
            <div style={{ color: "var(--muted)", fontSize: 12 }}>
              Commands: <code>gen</code>, <code>done</code>, <code>check</code>, <code>review</code>, <code>repair</code>, <code>validate</code>
            </div>
          </div>
        </div>

        <div style={{ border: "1px solid var(--border)", background: "var(--panel)", borderRadius: 16, padding: 14 }}>
          <div style={{ fontWeight: 700, marginBottom: 10 }}>Output</div>
          {error ? (
            <pre style={{ margin: 0, whiteSpace: "pre-wrap", color: "var(--danger)" }}>{error}</pre>
          ) : lastKicadProPath ? (
            <div style={{ color: "var(--text)" }}>
              <code>{lastKicadProPath}</code>
            </div>
          ) : (
            <div style={{ color: "var(--muted)" }}>
              {lastJsonPath ? `Current project JSON: ${lastJsonPath}` : "No generation output yet."}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

