/**
 * Drift dashboard Zustand store.
 *
 * Follows the SVAP pattern: flat state + action methods, each fetch
 * sets loading/error state appropriately.
 */

import { create } from "zustand";
import { apiGet, apiPost } from "./api";
import type {
  ProjectSummary,
  ProjectDetail,
  LibraryData,
  ArtifactDetail,
  LibraryGitStatus,
} from "../types";

// ── Store shape ─────────────────────────────────────────────────────────

export interface DriftStore {
  // Data slices
  projects: ProjectSummary[];
  selectedProject: ProjectDetail | null;
  library: LibraryData | null;
  selectedArtifact: ArtifactDetail | null;
  gitStatus: LibraryGitStatus | null;

  // Status
  loading: boolean;
  error: string | null;
  gitLoading: boolean;
  gitError: string | null;

  // Actions
  fetchProjects: () => Promise<void>;
  fetchProject: (name: string) => Promise<void>;
  fetchLibrary: () => Promise<void>;
  fetchArtifact: (id: string) => Promise<void>;
  clearSelection: () => void;
  fetchGitStatus: () => Promise<void>;
  gitCommit: () => Promise<string>;
  gitSetRemote: (url: string) => Promise<string>;
  gitPush: () => Promise<string>;
  gitPull: () => Promise<string>;
}

// ── Store ────────────────────────────────────────────────────────────────

export const useDriftStore = create<DriftStore>((set) => ({
  // Data — empty defaults
  projects: [],
  selectedProject: null,
  library: null,
  selectedArtifact: null,
  gitStatus: null,

  // Status
  loading: false,
  error: null,
  gitLoading: false,
  gitError: null,

  // Actions
  fetchProjects: async () => {
    set({ loading: true, error: null });
    try {
      const data = await apiGet<{ projects: ProjectSummary[] }>("/projects");
      set({ projects: data.projects, loading: false });
    } catch (err) {
      set({
        error: (err as Error).message || "Failed to fetch projects",
        loading: false,
      });
    }
  },

  fetchProject: async (name: string) => {
    set({ loading: true, error: null, selectedProject: null });
    try {
      const data = await apiGet<ProjectDetail>(`/projects/${name}`);
      set({ selectedProject: data, loading: false });
    } catch (err) {
      set({
        error: (err as Error).message || "Failed to fetch project",
        loading: false,
      });
    }
  },

  fetchLibrary: async () => {
    set({ loading: true, error: null });
    try {
      const data = await apiGet<LibraryData>("/library");
      set({ library: data, loading: false });
    } catch (err) {
      set({
        error: (err as Error).message || "Failed to fetch library",
        loading: false,
      });
    }
  },

  fetchArtifact: async (id: string) => {
    set({ loading: true, error: null, selectedArtifact: null });
    try {
      const data = await apiGet<ArtifactDetail>(`/library/artifacts/${id}`);
      set({ selectedArtifact: data, loading: false });
    } catch (err) {
      set({
        error: (err as Error).message || "Failed to fetch artifact",
        loading: false,
      });
    }
  },

  clearSelection: () => {
    set({ selectedProject: null, selectedArtifact: null, error: null });
  },

  // Git actions
  fetchGitStatus: async () => {
    set({ gitLoading: true, gitError: null });
    try {
      const data = await apiGet<LibraryGitStatus>("/library/git-status");
      set({ gitStatus: data, gitLoading: false });
    } catch (err) {
      set({
        gitError: (err as Error).message || "Failed to fetch git status",
        gitLoading: false,
      });
    }
  },

  gitCommit: async () => {
    set({ gitLoading: true, gitError: null });
    try {
      const data = await apiPost<{ message: string }>("/library/git-commit");
      const status = await apiGet<LibraryGitStatus>("/library/git-status");
      set({ gitStatus: status, gitLoading: false });
      return data.message;
    } catch (err) {
      const msg = (err as Error).message || "Commit failed";
      set({ gitError: msg, gitLoading: false });
      return msg;
    }
  },

  gitSetRemote: async (url: string) => {
    set({ gitLoading: true, gitError: null });
    try {
      const data = await apiPost<{ message: string }>("/library/git-remote", { url });
      const status = await apiGet<LibraryGitStatus>("/library/git-status");
      set({ gitStatus: status, gitLoading: false });
      return data.message;
    } catch (err) {
      const msg = (err as Error).message || "Failed to set remote";
      set({ gitError: msg, gitLoading: false });
      return msg;
    }
  },

  gitPush: async () => {
    set({ gitLoading: true, gitError: null });
    try {
      const data = await apiPost<{ message: string }>("/library/git-push");
      const status = await apiGet<LibraryGitStatus>("/library/git-status");
      set({ gitStatus: status, gitLoading: false });
      return data.message;
    } catch (err) {
      const msg = (err as Error).message || "Push failed";
      set({ gitError: msg, gitLoading: false });
      return msg;
    }
  },

  gitPull: async () => {
    set({ gitLoading: true, gitError: null });
    try {
      const data = await apiPost<{ message: string }>("/library/git-pull");
      const [status] = await Promise.all([
        apiGet<LibraryGitStatus>("/library/git-status"),
        apiGet<LibraryData>("/library").then((lib) => set({ library: lib })),
      ]);
      set({ gitStatus: status, gitLoading: false });
      return data.message;
    } catch (err) {
      const msg = (err as Error).message || "Pull failed";
      set({ gitError: msg, gitLoading: false });
      return msg;
    }
  },
}));
