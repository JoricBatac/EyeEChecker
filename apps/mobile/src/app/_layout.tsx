import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Stack, useRootNavigationState, useRouter, useSegments } from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';
import { useEffect, useRef } from 'react';
import { AppState, Pressable, Text } from 'react-native';

import { useCheck } from '@/lib/check';
import { useSettings } from '@/lib/settings';
import { colors } from '@/lib/ui';

SplashScreen.preventAutoHideAsync();
const queryClient = new QueryClient({ defaultOptions: { queries: { retry: 1 } } });
// An unfinished check (and its photos) is discarded after this long in the background.
const IDLE_DISCARD_MS = 15 * 60 * 1000;

function LocaleToggle() {
  const { locale, setLocale } = useSettings();
  return (
    <Pressable onPress={() => setLocale(locale === 'en' ? 'fil' : 'en')} hitSlop={10}>
      <Text style={{ color: colors.primary, fontWeight: '600' }}>{locale === 'en' ? 'EN' : 'FIL'}</Text>
    </Pressable>
  );
}

function useGate() {
  const { settings, hydrated, hydrate } = useSettings();
  const segments = useSegments();
  const router = useRouter();
  const navReady = !!useRootNavigationState()?.key;
  const backgroundedAt = useRef<number | null>(null);

  useEffect(() => {
    hydrate().finally(() => SplashScreen.hideAsync());
  }, [hydrate]);

  useEffect(() => {
    // Navigating before the root navigator has mounted crashes Expo Router.
    if (navReady && hydrated && !settings && segments[0] !== 'setup') router.replace('/setup');
  }, [navReady, hydrated, settings, segments, router]);

  useEffect(() => {
    const sub = AppState.addEventListener('change', (state) => {
      if (state === 'background') backgroundedAt.current = Date.now();
      if (state === 'active' && backgroundedAt.current && Date.now() - backgroundedAt.current > IDLE_DISCARD_MS) {
        useCheck.getState().reset();
        router.dismissTo('/');
      }
    });
    return () => sub.remove();
  }, [router]);
}

export default function RootLayout() {
  useGate();
  return (
    <QueryClientProvider client={queryClient}>
      <Stack
        screenOptions={{
          headerRight: () => <LocaleToggle />,
          headerTintColor: colors.primary,
          // iOS 26 draws a floating, see-through header by default; keep it solid so fields never sit under it.
          headerTransparent: false,
          headerStyle: { backgroundColor: colors.bg },
          headerShadowVisible: false,
          headerBlurEffect: undefined,
        }}>
        <Stack.Screen name="index" options={{ title: 'ScanAssist' }} />
        <Stack.Screen name="setup" options={{ title: 'Setup' }} />
        <Stack.Screen name="check/photo" options={{ title: 'New check' }} />
        <Stack.Screen name="check/result" options={{ title: 'Results' }} />
      </Stack>
    </QueryClientProvider>
  );
}
