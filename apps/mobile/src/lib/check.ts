import type { Lighting, QuickResult } from '@scanassist/shared';
import { File } from 'expo-file-system';
import { create } from 'zustand';

/**
 * The current check, held in memory only. Photo files sit in the app cache and are deleted when the check
 * ends (new check, or the app returning after inactivity).
 */
export type CheckPhoto = { uri: string; lighting: Lighting };

type CheckState = {
  photos: CheckPhoto[];
  age: number | null;
  answers: Record<string, unknown>;
  result: QuickResult | null;
  set: (patch: Partial<Pick<CheckState, 'age' | 'answers' | 'result'>>) => void;
  addPhoto: (p: CheckPhoto) => void;
  updatePhoto: (index: number, patch: Partial<CheckPhoto>) => void;
  removePhoto: (index: number) => void;
  reset: () => void;
};

export function deleteFile(uri: string | null | undefined) {
  if (!uri) return;
  try {
    const f = new File(uri);
    if (f.exists) f.delete();
  } catch {
    // already gone
  }
}

export const useCheck = create<CheckState>((set, get) => ({
  photos: [],
  age: null,
  answers: {},
  result: null,
  set: (patch) => set(patch),
  addPhoto: (p) => set((s) => ({ photos: [...s.photos, p], result: null })),
  updatePhoto: (i, patch) => set((s) => ({ photos: s.photos.map((p, j) => (j === i ? { ...p, ...patch } : p)), result: null })),
  removePhoto: (i) =>
    set((s) => {
      deleteFile(s.photos[i]?.uri);
      return { photos: s.photos.filter((_, j) => j !== i), result: null };
    }),
  reset: () => {
    get().photos.forEach((p) => deleteFile(p.uri));
    set({ photos: [], age: null, answers: {}, result: null });
  },
}));
