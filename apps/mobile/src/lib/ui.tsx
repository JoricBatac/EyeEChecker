import type { ReactNode } from 'react';
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  type TextInputProps,
  View,
  type ViewStyle,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

export const colors = {
  bg: '#F6F7F9',
  card: '#FFFFFF',
  text: '#14171A',
  muted: '#5F6670',
  border: '#DDE1E6',
  primary: '#0B6E99',
  primaryText: '#FFFFFF',
  urgent: '#B42318',
  urgentBg: '#FEF3F2',
  soon: '#B54708',
  soonBg: '#FFFAEB',
  ok: '#067647',
  okBg: '#ECFDF3',
  aiBg: '#EEF4FF',
  ai: '#3538CD',
};

export function Screen({ children, scroll = true }: { children: ReactNode; scroll?: boolean }) {
  return (
    <SafeAreaView style={styles.screen} edges={['bottom', 'left', 'right']}>
      {scroll ? (
        <ScrollView
          contentContainerStyle={styles.content}
          keyboardShouldPersistTaps="handled"
          contentInsetAdjustmentBehavior="automatic">

          {children}
        </ScrollView>
      ) : (
        <View style={[styles.content, { flex: 1 }]}>{children}</View>
      )}
    </SafeAreaView>
  );
}

export function Card({ children, style }: { children: ReactNode; style?: ViewStyle }) {
  return <View style={[styles.card, style]}>{children}</View>;
}

export function H1({ children }: { children: ReactNode }) {
  return <Text style={styles.h1}>{children}</Text>;
}

export function H2({ children }: { children: ReactNode }) {
  return <Text style={styles.h2}>{children}</Text>;
}

export function Muted({ children }: { children: ReactNode }) {
  return <Text style={styles.muted}>{children}</Text>;
}

export function Body({ children, bold }: { children: ReactNode; bold?: boolean }) {
  return <Text style={[styles.body, bold && { fontWeight: '600' }]}>{children}</Text>;
}

export function Button({
  title,
  onPress,
  variant = 'primary',
  disabled,
  loading,
}: {
  title: string;
  onPress: () => void;
  variant?: 'primary' | 'secondary' | 'danger';
  disabled?: boolean;
  loading?: boolean;
}) {
  const bg = variant === 'primary' ? colors.primary : variant === 'danger' ? colors.urgent : colors.card;
  const fg = variant === 'secondary' ? colors.primary : colors.primaryText;
  return (
    <Pressable
      accessibilityRole="button"
      onPress={onPress}
      disabled={disabled || loading}
      style={({ pressed }) => [
        styles.button,
        { backgroundColor: bg, opacity: disabled ? 0.45 : pressed ? 0.8 : 1 },
        variant === 'secondary' && { borderWidth: 1, borderColor: colors.primary },
      ]}>
      {loading ? <ActivityIndicator color={fg} /> : <Text style={[styles.buttonText, { color: fg }]}>{title}</Text>}
    </Pressable>
  );
}

export function Chip({ label, selected, onPress }: { label: string; selected: boolean; onPress: () => void }) {
  return (
    <Pressable
      accessibilityRole="checkbox"
      accessibilityState={{ checked: selected }}
      onPress={onPress}
      style={[styles.chip, selected && { backgroundColor: colors.primary, borderColor: colors.primary }]}>
      <Text style={{ color: selected ? colors.primaryText : colors.text, fontSize: 15 }}>{label}</Text>
    </Pressable>
  );
}

export function Field({ label, required, children }: { label: string; required?: boolean; children: ReactNode }) {
  return (
    <View style={{ marginBottom: 16 }}>
      <Text style={styles.label}>
        {label}
        {required ? <Text style={{ color: colors.urgent }}> *</Text> : null}
      </Text>
      {children}
    </View>
  );
}

export function Input(props: TextInputProps) {
  return <TextInput placeholderTextColor={colors.muted} {...props} style={[styles.input, props.style]} />;
}

export function Banner({ tone, children }: { tone: 'urgent' | 'soon' | 'ok' | 'ai'; children: ReactNode }) {
  const map = {
    urgent: [colors.urgentBg, colors.urgent],
    soon: [colors.soonBg, colors.soon],
    ok: [colors.okBg, colors.ok],
    ai: [colors.aiBg, colors.ai],
  } as const;
  const [bg, fg] = map[tone];
  return <View style={[styles.banner, { backgroundColor: bg, borderLeftColor: fg }]}>{children}</View>;
}

export function Row({ children, gap = 8 }: { children: ReactNode; gap?: number }) {
  return <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap, alignItems: 'center' }}>{children}</View>;
}

export function Loading() {
  return (
    <View style={{ flex: 1, justifyContent: 'center', alignItems: 'center', padding: 32 }}>
      <ActivityIndicator size="large" color={colors.primary} />
    </View>
  );
}

export function ErrorText({ error }: { error: unknown }) {
  if (!error) return null;
  return <Text style={{ color: colors.urgent, marginVertical: 8 }}>{error instanceof Error ? error.message : String(error)}</Text>;
}

export const urgencyTone = (u: string | null | undefined) => (u === 'urgent' ? 'urgent' : u === 'soon' ? 'soon' : 'ok');

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 16, gap: 12 },
  card: { backgroundColor: colors.card, borderRadius: 12, padding: 16, borderWidth: 1, borderColor: colors.border, gap: 8 },
  h1: { fontSize: 22, fontWeight: '700', color: colors.text },
  h2: { fontSize: 17, fontWeight: '600', color: colors.text },
  body: { fontSize: 15, color: colors.text, lineHeight: 21 },
  muted: { fontSize: 13, color: colors.muted },
  label: { fontSize: 14, fontWeight: '600', color: colors.text, marginBottom: 6 },
  button: { minHeight: 48, borderRadius: 10, paddingHorizontal: 16, alignItems: 'center', justifyContent: 'center' },
  buttonText: { fontSize: 16, fontWeight: '600' },
  chip: { paddingVertical: 9, paddingHorizontal: 14, borderRadius: 20, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.card },
  input: { minHeight: 46, borderWidth: 1, borderColor: colors.border, borderRadius: 10, paddingHorizontal: 12, fontSize: 16, backgroundColor: colors.card, color: colors.text },
  banner: { borderLeftWidth: 4, borderRadius: 8, padding: 12, gap: 6 },
});
