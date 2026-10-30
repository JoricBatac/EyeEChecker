import { createAssistClient, type Pack } from '@scanassist/shared';
import { useQuery } from '@tanstack/react-query';

import { useSettings } from './settings';

// On a phone with Expo Go, set EXPO_PUBLIC_API_URL to your computer's LAN address, e.g. http://192.168.1.20:8000
export const API_URL = process.env.EXPO_PUBLIC_API_URL ?? 'http://localhost:8000';

export const api = createAssistClient({
  baseUrl: API_URL,
  getCode: () => useSettings.getState().settings?.code ?? null,
});

export function usePack(): { pack: Pack | undefined; isLoading: boolean; error: unknown } {
  const profession = useSettings((s) => s.settings?.profession);
  const q = useQuery({
    queryKey: ['config', profession],
    queryFn: () => api.config(profession),
    staleTime: 30 * 60 * 1000,
  });
  return { pack: q.data?.pack, isLoading: q.isLoading, error: q.error };
}

export function useLocale() {
  return useSettings((s) => s.locale);
}
