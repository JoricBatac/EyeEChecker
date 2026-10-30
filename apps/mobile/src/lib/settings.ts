import * as SecureStore from 'expo-secure-store';
import { create } from 'zustand';

const KEY = 'scanassist.settings';

/** Device settings. Clinician and clinic details are used only to sign PDFs made on this phone. */
export type Settings = {
  code: string;
  clinic: string;
  clinicianName: string;
  license: string;
  profession: 'optometrist' | 'physician' | 'ophthalmologist' | 'nurse' | 'other';
  clinicName: string;
  clinicAddress: string;
};

type State = {
  settings: Settings | null;
  hydrated: boolean;
  locale: 'en' | 'fil';
  hydrate: () => Promise<void>;
  save: (s: Settings) => Promise<void>;
  clear: () => Promise<void>;
  setLocale: (l: 'en' | 'fil') => void;
};

export const useSettings = create<State>((set) => ({
  settings: null,
  hydrated: false,
  locale: 'en',
  hydrate: async () => {
    const raw = await SecureStore.getItemAsync(KEY);
    set({ settings: raw ? JSON.parse(raw) : null, hydrated: true });
  },
  save: async (s) => {
    await SecureStore.setItemAsync(KEY, JSON.stringify(s));
    set({ settings: s });
  },
  clear: async () => {
    await SecureStore.deleteItemAsync(KEY);
    set({ settings: null });
  },
  setLocale: (locale) => set({ locale }),
}));
