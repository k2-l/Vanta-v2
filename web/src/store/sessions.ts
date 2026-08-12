import { create } from "zustand";
import type { Session } from "@/shared/lib/api";

type SessionsState = {
  sessions: Session[];
  setSessions: (sessions: Session[]) => void;
};

export const useSessions = create<SessionsState>((set) => ({
  sessions: [],
  setSessions: (sessions) => set({ sessions }),
}));
