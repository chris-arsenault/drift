/**
 * Drift dashboard Zustand store.
 *
 * Follows the SVAP pattern: flat state + action methods, each fetch
 * sets loading/error state appropriately.
 */

import { create } from "zustand";
import { apiGet } from "./api";
import type {
  ProjectSummary,
  ProjectDetail,
  LibraryData,
  ArtifactDetail,
} from "../types";

// ── Store shape ─────────────────────────────────────────────────────────

export interface DriftStore {
  // Data slices
  projects: ProjectSummary[];
  selectedProject: ProjectDetail | null;
  library: LibraryData | null;
  selectedArtifact: ArtifactDetail | null;

  // Status
  loading: boolean;
  error: string | null;

  // Actions
  fetchProjects: () => Promise<void>;
  fetchProject: (name: string) => Promise<void>;
  fetchLibrary: () => Promise<void>;
  fetchArtifact: (id: string) => Promise<void>;
  clearSelection: () => void;
}

// ── Store ────────────────────────────────────────────────────────────────

export const useDriftStore = create<DriftStore>((set) => ({
  // Data — empty defaults
  projects: [],
  selectedProject: null,
  library: null,
  selectedArtifact: null,

  // Status
  loading: false,
  error: null,

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
}));
