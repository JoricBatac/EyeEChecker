import { useQueryClient } from '@tanstack/react-query';
import { useRouter } from 'expo-router';
import { useState } from 'react';

import { api, API_URL } from '@/lib/api';
import { useSettings, type Settings } from '@/lib/settings';
import { Body, Button, Card, Chip, ErrorText, Field, H1, Input, Muted, Row, Screen } from '@/lib/ui';

const PROFESSIONS: Settings['profession'][] = ['physician', 'optometrist', 'ophthalmologist', 'nurse', 'other'];

export default function Setup() {
  const router = useRouter();
  const qc = useQueryClient();
  const { settings, save, clear } = useSettings();
  const [form, setForm] = useState<Settings>(
    settings ?? {
      // Development builds can pre-fill these from apps/mobile/.env to skip typing during testing.
      code: (__DEV__ && process.env.EXPO_PUBLIC_DEV_ACCESS_CODE) || '',
      clinic: '',
      clinicianName: (__DEV__ && process.env.EXPO_PUBLIC_DEV_CLINICIAN) || '',
      license: '',
      profession: 'physician',
      clinicName: '',
      clinicAddress: '',
    },
  );
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const update = (patch: Partial<Settings>) => setForm({ ...form, ...patch });

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const code = form.code.trim().toUpperCase();
      const cfg = await api.config(form.profession, code);
      await save({ ...form, code, clinic: cfg.clinic, clinicName: form.clinicName || cfg.clinic });
      await qc.invalidateQueries();
      router.replace('/');
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Screen>
      <H1>{settings ? 'Settings' : 'Welcome to ScanAssist'}</H1>
      <Muted>
        Patient details stay on this phone. Photos are sent only for analysis and are not stored on the server.
      </Muted>
      <Card>
        <Field label="Clinic access code" required>
          <Input value={form.code} onChangeText={(v) => update({ code: v })} autoCapitalize="characters" placeholder="XXXX-XXXX-XXXX" />
        </Field>
        <Field label="Your name (optional)">
          <Input value={form.clinicianName} onChangeText={(v) => update({ clinicianName: v })} autoCapitalize="words" />
        </Field>
        <Field label="Profession" required>
          <Row>
            {PROFESSIONS.map((p) => (
              <Chip key={p} label={p} selected={form.profession === p} onPress={() => update({ profession: p })} />
            ))}
          </Row>
        </Field>
        <Field label="License number">
          <Input value={form.license} onChangeText={(v) => update({ license: v })} />
        </Field>
        <Field label="Clinic name (on reports)">
          <Input value={form.clinicName} onChangeText={(v) => update({ clinicName: v })} />
        </Field>
        <Field label="Clinic address">
          <Input value={form.clinicAddress} onChangeText={(v) => update({ clinicAddress: v })} />
        </Field>
        <ErrorText error={error} />
        <Button title="Save" onPress={submit} loading={busy} disabled={!form.code.trim()} />
      </Card>
      {settings && <Button title="Remove this device's settings" variant="danger" onPress={() => void clear()} />}
      <Body> </Body>
      <Muted>Server: {API_URL}</Muted>
    </Screen>
  );
}
