import { useRouter } from 'expo-router';
import { View } from 'react-native';

import { usePack } from '@/lib/api';
import { useCheck } from '@/lib/check';
import { useSettings } from '@/lib/settings';
import { Body, Button, Card, ErrorText, H1, Muted, Screen } from '@/lib/ui';

export default function Home() {
  const router = useRouter();
  const settings = useSettings((s) => s.settings);
  const { pack, error, isLoading } = usePack();
  const reset = useCheck((s) => s.reset);

  return (
    <Screen>
      <H1>ScanAssist</H1>
      <Muted>
        {settings?.clinicianName ? `${settings.clinicianName} · ` : ''}
        {settings?.clinic}
      </Muted>
      <ErrorText error={error} />
      <Button
        title="New check"
        loading={isLoading}
        disabled={!pack}
        onPress={() => {
          reset();
          router.push('/check/photo');
        }}
      />
      <Card>
        <Body bold>How it works</Body>
        <Muted>1. Take or upload a photo of the eye. Mark it as dim light or flash if it was.</Muted>
        <Muted>2. Optionally add age and symptoms.</Muted>
        <Muted>3. Get the likely causes with probabilities and why.</Muted>
        <Muted>Photos are not stored.</Muted>
      </Card>
      <View style={{ flex: 1 }} />
      <Button title="Settings" variant="secondary" onPress={() => router.push('/setup')} />
    </Screen>
  );
}
