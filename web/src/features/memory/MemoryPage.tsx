import { useCallback, useEffect, useRef, useState } from "react";
import { api, type MemoryItem } from "@/shared/lib/api";
import { useChat } from "@/store/chat";
import { useSessions } from "@/store/sessions";

export function MemoryPage() {
  const currentId = useChat((s) => s.currentSessionId);
  const sessions = useSessions((s) => s.sessions);

  const [query, setQuery]         = useState("");
  const [sessionMems, setSessionMems] = useState<MemoryItem[]>([]);
  const [searchResults, setSearchResults] = useState<MemoryItem[] | null>(null);
  const [loading, setLoading]     = useState(false);
  const [selected, setSelected]   = useState<MemoryItem | null>(null);
  const [deleting, setDeleting]   = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const loadSession = useCallback(async () => {
    if (!currentId) return;
    try {
      const list = await api.memoryList(currentId, 100);
      setSessionMems(list);
    } catch {
      setSessionMems([]);
    }
  }, [currentId]);

  useEffect(() => { loadSession(); }, [loadSession]);

  async function doSearch() {
    const q = query.trim();
    if (!q) { setSearchResults(null); return; }
    setLoading(true);
    try {
      const r = await api.memorySearch(q, 20);
      setSearchResults(r);
    } catch {
      setSearchResults([]);
    } finally {
      setLoading(false);
    }
  }

  function clearSearch() {
    setQuery("");
    setSearchResults(null);
    setSelected(null);
    inputRef.current?.focus();
  }

  async function deleteMemory(id: string) {
    if (deleting) return;
    setDeleting(id);
    try {
      await (api as any).deleteMemory?.(id);
    } catch {}
    setSessionMems((prev) => prev.filter((m) => m.id !== id));
    setSearchResults((prev) => prev ? prev.filter((m) => m.id !== id) : null);
    if (selected?.id === id) setSelected(null);
    setDeleting(null);
  }

  const displayList = searchResults ?? sessionMems;
  const isSearching = searchResults !== null;

  return (
    <div style={{
      flex: 1,
      display: "flex",
      flexDirection: "column",
      overflow: "hidden",
      background: "#F4F5F7",
    }}>

      {/* ── Header ──────────────────────────────────────────── */}
      <div style={{
        padding: "20px 28px 16px",
        background: "#FFFFFF",
        borderBottom: "1px solid #E2E5EA",
        flexShrink: 0,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12 }}>
          <span style={{ fontSize: 18, color: "#4F6EF7" }}>◌</span>
          <span style={{ fontSize: 15, fontWeight: 700, color: "#1A1D23" }}>经验记忆</span>
          <span style={{ fontSize: 11, color: "#9BA3AF", marginLeft: 4 }}>
            {isSearching
              ? `搜索结果 · ${displayList.length} 条`
              : (() => {
                  const title = sessions.find((s) => s.id === currentId)?.title;
                  const truncated = title && title.length > 20 ? title.slice(0, 20) + "…" : title;
                  return `当前会话 · ${sessionMems.length} 条${truncated ? ` · ${truncated}` : ""}`;
                })()}
          </span>
          <button
            onClick={loadSession}
            style={{ fontSize: 11, padding: "4px 10px", borderRadius: 7, background: "#4F6EF718", border: "1px solid #4F6EF744", color: "#4F6EF7", cursor: "pointer", fontFamily: "inherit", marginLeft: "auto" }}
          >
            ↻ 刷新
          </button>
        </div>

        {/* Search bar */}
        <div style={{ display: "flex", gap: 8 }}>
          <div style={{
            flex: 1,
            display: "flex",
            alignItems: "center",
            background: "#F9FAFB",
            border: "1px solid #E2E5EA",
            borderRadius: 10,
            padding: "0 12px",
            gap: 8,
          }}>
            <span style={{ fontSize: 12, color: "#C0C5CE" }}>⌕</span>
            <input
              ref={inputRef}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") doSearch();
                if (e.key === "Escape") clearSearch();
              }}
              placeholder="向量检索记忆… (Enter 搜索)"
              style={{
                flex: 1,
                background: "transparent",
                border: "none",
                outline: "none",
                fontSize: 12,
                color: "#374151",
                fontFamily: "inherit",
                padding: "9px 0",
              }}
            />
            {query && (
              <button
                onClick={clearSearch}
                style={{ background: "none", border: "none", color: "#C0C5CE", cursor: "pointer", fontSize: 12, padding: 0 }}
              >
                ✕
              </button>
            )}
          </div>
          <button
            onClick={doSearch}
            disabled={loading || !query.trim()}
            style={{
              padding: "0 18px",
              borderRadius: 10,
              background: "#4F6EF718",
              border: "1px solid #4F6EF744",
              color: "#4F6EF7",
              fontSize: 12,
              cursor: query.trim() && !loading ? "pointer" : "default",
              opacity: query.trim() && !loading ? 1 : 0.4,
              fontFamily: "inherit",
              flexShrink: 0,
            }}
          >
            {loading ? "检索中…" : "检索"}
          </button>
        </div>
      </div>

      {/* ── Body ────────────────────────────────────────────── */}
      <div style={{ flex: 1, display: "flex", overflow: "hidden", minHeight: 0 }}>

        {/* List */}
        <div style={{
          width: 340,
          flexShrink: 0,
          overflowY: "auto",
          padding: "12px",
          display: "flex",
          flexDirection: "column",
          gap: 8,
          borderRight: "1px solid #E2E5EA",
          background: "#FFFFFF",
        }}>
          {isSearching && (
            <div style={{
              fontSize: 9,
              letterSpacing: 1,
              color: "#B0B7C3",
              textTransform: "uppercase",
              padding: "2px 4px 6px",
            }}>
              向量检索结果
            </div>
          )}
          {!isSearching && sessionMems.length === 0 && (
            <div style={{ fontSize: 11, color: "#C0C5CE", textAlign: "center", marginTop: 32 }}>
              {currentId ? "当前会话暂无记忆" : "请先选择一个会话"}
            </div>
          )}
          {isSearching && displayList.length === 0 && (
            <div style={{ fontSize: 11, color: "#C0C5CE", textAlign: "center", marginTop: 32 }}>
              未找到相关记忆
            </div>
          )}
          {displayList.map((m) => (
            <MemoryCard
              key={m.id}
              item={m}
              selected={selected?.id === m.id}
              showDistance={isSearching}
              onClick={() => setSelected(m)}
              onDelete={() => deleteMemory(m.id)}
            />
          ))}
        </div>

        {/* Detail pane */}
        <div style={{
          flex: 1,
          overflowY: "auto",
          padding: "24px 32px",
        }}>
          {selected ? (
            <MemoryDetail item={selected} onDelete={() => deleteMemory(selected.id)} />
          ) : (
            <EmptyDetail />
          )}
        </div>
      </div>
    </div>
  );
}

function MemoryCard({
  item,
  selected,
  showDistance,
  onClick,
  onDelete,
}: {
  item: MemoryItem;
  selected: boolean;
  showDistance: boolean;
  onClick: () => void;
  onDelete?: () => void;
}) {
  const [hovered, setHovered] = useState(false);
  const meta = item.metadata as Record<string, unknown>;
  const type = meta.type as string | undefined;
  const tags = (meta.tags as string[] | undefined) ?? [];
  const accent = type === "failure" ? "#F59E0B" : type === "success" ? "#10B981" : "#C0C5CE";

  return (
    <div
      onClick={onClick}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        background: selected ? "#4F6EF708" : "#F9FAFB",
        border: `1px solid ${selected ? "#4F6EF766" : "#E2E5EA"}`,
        borderLeft: `3px solid ${selected ? "#4F6EF7" : accent}`,
        borderRadius: 10,
        padding: "10px 12px",
        cursor: "pointer",
        display: "flex",
        flexDirection: "column",
        gap: 5,
        transition: "all 0.12s",
        position: "relative",
      }}
    >
      {hovered && (
        <button
          onClick={(e) => { e.stopPropagation(); onDelete?.(); }}
          style={{ position: "absolute", top: 6, right: 6, background: "none", border: "none", cursor: "pointer", fontSize: 10, color: "#EF4444", opacity: 0.6, padding: 0, lineHeight: 1 }}
        >
          ✕
        </button>
      )}
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        {type && (
          <span style={{ fontSize: 9, fontWeight: 700, color: accent }}>
            {type === "failure" ? "⚠ 失败" : type === "success" ? "✓ 成功" : type}
          </span>
        )}
        {showDistance && item.distance != null && (
          <span style={{ marginLeft: "auto", fontSize: 9, color: "#C0C5CE" }}>
            {(1 - item.distance).toFixed(2)}
          </span>
        )}
      </div>
      <p style={{
        margin: 0,
        fontSize: 11,
        color: "#374151",
        lineHeight: 1.5,
        overflow: "hidden",
        display: "-webkit-box",
        WebkitLineClamp: 3,
        WebkitBoxOrient: "vertical" as unknown as "vertical",
      }}>
        {item.text}
      </p>
      {tags.length > 0 && (
        <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
          {tags.slice(0, 4).map((t) => (
            <span key={t} style={{ fontSize: 9, padding: "1px 6px", borderRadius: 99, background: "#4F6EF711", color: "#4F6EF7" }}>
              #{t}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function MemoryDetail({ item, onDelete }: { item: MemoryItem; onDelete?: () => void }) {
  const meta = item.metadata as Record<string, unknown>;
  const type = meta.type as string | undefined;
  const tags = (meta.tags as string[] | undefined) ?? [];
  const accent = type === "failure" ? "#F59E0B" : type === "success" ? "#10B981" : "#C0C5CE";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        {type && (
          <span style={{
            fontSize: 11,
            fontWeight: 700,
            color: accent,
            background: accent + "18",
            padding: "3px 10px",
            borderRadius: 99,
          }}>
            {type === "failure" ? "⚠ 失败教训" : type === "success" ? "✓ 成功案例" : type}
          </span>
        )}
        <span style={{ fontSize: 10, color: "#C0C5CE", fontFamily: "monospace" }}>{item.id}</span>
        <button
          onClick={onDelete}
          style={{ marginLeft: "auto", fontSize: 11, padding: "4px 10px", borderRadius: 6, background: "#EF444411", border: "1px solid #EF4444", color: "#EF4444", cursor: "pointer" }}
        >
          ✕ 删除
        </button>
      </div>

      <div style={{
        background: "#FFFFFF",
        border: "1px solid #E2E5EA",
        borderLeft: `4px solid ${accent}`,
        borderRadius: 10,
        padding: "20px 24px",
        fontSize: 13,
        lineHeight: 1.8,
        color: "#374151",
        whiteSpace: "pre-wrap",
      }}>
        {item.text}
      </div>

      {tags.length > 0 && (
        <div>
          <div style={{ fontSize: 10, color: "#9BA3AF", letterSpacing: 1, marginBottom: 8 }}>TAGS</div>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {tags.map((t) => (
              <span key={t} style={{ fontSize: 11, padding: "3px 10px", borderRadius: 99, background: "#4F6EF711", color: "#4F6EF7", border: "1px solid #4F6EF733" }}>
                #{t}
              </span>
            ))}
          </div>
        </div>
      )}

      {Object.keys(meta).filter((k) => k !== "type" && k !== "tags").length > 0 && (
        <div>
          <div style={{ fontSize: 10, color: "#9BA3AF", letterSpacing: 1, marginBottom: 8 }}>元数据</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {Object.entries(meta)
              .filter(([k]) => k !== "type" && k !== "tags")
              .map(([k, v]) => (
                <div key={k} style={{ display: "flex", gap: 12, fontSize: 11 }}>
                  <span style={{ color: "#9BA3AF", fontFamily: "monospace", minWidth: 120 }}>{k}</span>
                  <span style={{ color: "#374151" }}>{String(v)}</span>
                </div>
              ))}
          </div>
        </div>
      )}
    </div>
  );
}

function EmptyDetail() {
  return (
    <div style={{
      height: "100%",
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      justifyContent: "center",
      gap: 12,
      color: "#C0C5CE",
    }}>
      <span style={{ fontSize: 36 }}>◌</span>
      <span style={{ fontSize: 12 }}>选择左侧记忆查看详情</span>
      <span style={{ fontSize: 11 }}>或输入关键词进行向量检索</span>
    </div>
  );
}
