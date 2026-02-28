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
  ProjectSyncStatus,
  ClusterData,
} from "../types";

// ── Store shape ─────────────────────────────────────────────────────────

export interface DriftStore {
  // Data slices
  projects: ProjectSummary[];
  selectedProject: ProjectDetail | null;
  library: LibraryData | null;
  selectedArtifact: ArtifactDetail | null;
  gitStatus: LibraryGitStatus | null;
  syncStatus: ProjectSyncStatus | null;
  clusterData: ClusterData | null;

  // Status
  loading: boolean;
  error: string | null;
  gitLoading: boolean;
  gitError: string | null;
  syncLoading: boolean;
  syncError: string | null;
  clusterLoading: boolean;
  clusterError: string | null;

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
  fetchSyncStatus: (name: string) => Promise<void>;
  syncPull: (name: string) => Promise<string>;
  syncPush: (name: string) => Promise<string>;
  toggleExclude: (name: string, artifactId: string, excluded: boolean) => Promise<void>;
  fetchClusters: (name: string) => Promise<void>;
}

// ── Store ────────────────────────────────────────────────────────────────

export const useDriftStore = create<DriftStore>((set) => ({
  // Data — empty defaults
  projects: [],
  selectedProject: null,
  library: null,
  selectedArtifact: null,
  gitStatus: null,
  syncStatus: null,
  clusterData: null,

  // Status
  loading: false,
  error: null,
  gitLoading: false,
  gitError: null,
  syncLoading: false,
  syncError: null,
  clusterLoading: false,
  clusterError: null,

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

  // Sync actions
  fetchSyncStatus: async (name: string) => {
    set({ syncLoading: true, syncError: null });
    try {
      const data = await apiGet<ProjectSyncStatus>(`/projects/${name}/sync`);
      set({ syncStatus: data, syncLoading: false });
    } catch (err) {
      set({
        syncError: (err as Error).message || "Failed to fetch sync status",
        syncLoading: false,
      });
    }
  },

  syncPull: async (name: string) => {
    set({ syncLoading: true, syncError: null });
    try {
      const data = await apiPost<{ message: string }>(`/projects/${name}/sync/pull`);
      const status = await apiGet<ProjectSyncStatus>(`/projects/${name}/sync`);
      set({ syncStatus: status, syncLoading: false });
      return data.message;
    } catch (err) {
      const msg = (err as Error).message || "Pull failed";
      set({ syncError: msg, syncLoading: false });
      return msg;
    }
  },

  syncPush: async (name: string) => {
    set({ syncLoading: true, syncError: null });
    try {
      const data = await apiPost<{ message: string }>(`/projects/${name}/sync/push`);
      const status = await apiGet<ProjectSyncStatus>(`/projects/${name}/sync`);
      set({ syncStatus: status, syncLoading: false });
      return data.message;
    } catch (err) {
      const msg = (err as Error).message || "Push failed";
      set({ syncError: msg, syncLoading: false });
      return msg;
    }
  },

  toggleExclude: async (name: string, artifactId: string, excluded: boolean) => {
    set({ syncLoading: true, syncError: null });
    try {
      await apiPost(`/projects/${name}/sync/exclude`, { artifactId, excluded });
      const status = await apiGet<ProjectSyncStatus>(`/projects/${name}/sync`);
      set({ syncStatus: status, syncLoading: false });
    } catch (err) {
      set({
        syncError: (err as Error).message || "Failed to toggle exclude",
        syncLoading: false,
      });
    }
  },

  fetchClusters: async (name: string) => {
    set({ clusterLoading: true, clusterError: null });
    try {
      const data = await apiGet<ClusterData>(`/projects/${name}/clusters`);
      set({ clusterData: data, clusterLoading: false });
    } catch (err) {
      set({
        clusterError: (err as Error).message || "Failed to fetch clusters",
        clusterLoading: false,
      });
    }
  },
}));
