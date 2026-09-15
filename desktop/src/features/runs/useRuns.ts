/**
 * 运行数据层（Plan G2）——run ≈ session；详情用 phases 快照（REST）重建投影。
 * 列表复用 chat 的 sessions 查询缓存；每个 run 的状态/步骤由其 phases 快照派生。
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ipc } from "@/ipc/client";
import { runSubscribe } from "@/ipc/run";
import { useConnection } from "@/stores/connection";
import { toClientError } from "@/contracts/errors";
import type { PhaseSnapshotRow, RunEventWire, StreamPacket } from "@/contracts/stream";
import {
  applyPacket,
  applyPhasesSnapshot,
  emptyProjection,
  type RunProjection,
} from "./projection";

export function useSessionPhases(sessionId: string | undefined, active = true) {
  const connectionId = useConnection((s) => s.activeConnectionId);
  const authed = useConnection((s) => s.auth.authenticated);
  const runSnapshot = useConnection((s) => s.capabilities.runSnapshot);
  return useQuery<PhaseSnapshotRow[]>({
    queryKey: ["phases", connectionId, sessionId],
    enabled: Boolean(active && connectionId && authed && runSnapshot && sessionId),
    staleTime: 20_000,
    queryFn: async () => {
      const result = await ipc("api_request", {
        connectionId: connectionId!,
        operation: { op: "sessions.phases", sessionId: sessionId! },
      });
      return Array.isArray(result) ? (result as PhaseSnapshotRow[]) : [];
    },
  });
}

export function useSessionRunEvents(sessionId: string | undefined, active = true) {
  const connectionId = useConnection((s) => s.activeConnectionId);
  const authed = useConnection((s) => s.auth.authenticated);
  const runSnapshot = useConnection((s) => s.capabilities.runSnapshot);
  const runHistory = useConnection((s) => s.capabilities.runHistory);
  return useQuery<RunEventWire[]>({
    queryKey: ["run-events", connectionId, sessionId],
    enabled: Boolean(active && connectionId && authed && runSnapshot && runHistory && sessionId),
    placeholderData: [],
    staleTime: 5_000,
    queryFn: async () => {
      const result = await ipc("api_request", {
        connectionId: connectionId!,
        operation: { op: "sessions.events", sessionId: sessionId!, limit: 2000 },
      });
      return Array.isArray(result) ? (result as RunEventWire[]) : [];
    },
  });
}

export function projectionFromHistory(
  sessionId: string,
  phases: PhaseSnapshotRow[],
  events: RunEventWire[],
): RunProjection {
  const history = [...events]
    .sort((a, b) => a.seq - b.seq)
    .reduce(
      (projection, event) =>
        applyPacket(projection, { event: event.event, data: event.data } as unknown as StreamPacket),
      emptyProjection(sessionId),
    );
  return applyPhasesSnapshot(history, phases);
}

/**
 * run 详情投影：REST 快照负责首屏/重连基线，run_subscribe 负责选中运行的持续更新。
 * 卸载或切换 run 时主动停止 Rust 侧订阅，避免后台轮询泄漏。
 */
export function useRunProjection(sessionId: string | undefined, active = true) {
  const connectionId = useConnection((s) => s.activeConnectionId);
  const authed = useConnection((s) => s.auth.authenticated);
  const runSnapshot = useConnection((s) => s.capabilities.runSnapshot);
  const runHistory = useConnection((s) => s.capabilities.runHistory);
  const phases = useSessionPhases(sessionId, active);
  const events = useSessionRunEvents(sessionId, active);
  const baseline = useMemo(
    () =>
      sessionId && phases.data && events.data
        ? projectionFromHistory(sessionId, phases.data, events.data)
        : undefined,
    [events.data, phases.data, sessionId],
  );
  const [projection, setProjection] = useState<RunProjection>();
  const [subscribing, setSubscribing] = useState(false);
  const [subscriptionError, setSubscriptionError] = useState<string>();
  const [reconnectTick, setReconnectTick] = useState(0);
  const reconnectAttempts = useRef(0);

  useEffect(() => {
    reconnectAttempts.current = 0;
    setReconnectTick(0);
  }, [connectionId, sessionId]);

  useEffect(() => {
    setProjection(baseline);
    setSubscriptionError(undefined);
  }, [baseline]);

  useEffect(() => {
    if (!active || !connectionId || !authed || !runSnapshot || !sessionId || !baseline) return;
    // 历史终态 run 由 REST 快照完整呈现，无需保持轮询。
    if (baseline.phaseOrder.length > 0 && baseline.status !== "running" && baseline.status !== "queued") return;

    let disposed = false;
    let handleId: string | undefined;
    let reconnectTimer: ReturnType<typeof setTimeout> | undefined;
    const scheduleReconnect = () => {
      if (disposed || reconnectAttempts.current >= 3) return;
      const attempt = ++reconnectAttempts.current;
      const delay = Math.min(1000 * 2 ** (attempt - 1), 4000);
      reconnectTimer = setTimeout(() => {
        if (!disposed) setReconnectTick((value) => value + 1);
      }, delay);
    };
    setSubscribing(true);

    void runSubscribe(
      { connectionId, runId: sessionId, afterSeq: baseline.snapshotSeq },
      (packet) => {
        if (disposed) return;
        setProjection((current) => applyPacket(current ?? baseline, packet));
        if (packet.event === "snapshot") {
          reconnectAttempts.current = 0;
          setSubscriptionError(undefined);
          if (runHistory) void events.refetch();
        }
        if (packet.event === "client_error") {
          setSubscriptionError(toClientError(packet.data).message);
        }
        if (packet.event === "stream.closed") {
          setSubscribing(false);
          if (packet.data.reason === "failed" || packet.data.reason === "receiver_closed") scheduleReconnect();
        }
      },
    )
      .then((handle) => {
        if (disposed) {
          void ipc("stream_stop", { handleId: handle.handleId });
          return;
        }
        handleId = handle.handleId;
      })
      .catch((cause) => {
        if (disposed) return;
        setSubscribing(false);
        setSubscriptionError(toClientError(cause).message);
        scheduleReconnect();
      });

    return () => {
      disposed = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (handleId) void ipc("stream_stop", { handleId });
    };
  }, [active, authed, baseline, connectionId, reconnectTick, runHistory, runSnapshot, sessionId]);

  const refetch = async () => {
    reconnectAttempts.current = 0;
    const result = runHistory
      ? await Promise.all([phases.refetch(), events.refetch()])
      : await phases.refetch();
    setReconnectTick((value) => value + 1);
    return result;
  };

  return {
    projection,
    isLoading: phases.isLoading || events.isLoading,
    isError: phases.isError || events.isError || Boolean(subscriptionError),
    error:
      subscriptionError ??
      (phases.error ? toClientError(phases.error).message : undefined) ??
      (events.error ? toClientError(events.error).message : undefined),
    isLive: subscribing,
    refetch,
  };
}
