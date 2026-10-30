import { t, type ExplainedResult } from '@scanassist/shared';
import { useMutation } from '@tanstack/react-query';
import { Image } from 'expo-image';
import { useRouter } from 'expo-router';
import { useState } from 'react';
import { Pressable, ScrollView, View } from 'react-native';

import { cleanAnswers, FieldInput } from '@/components/ExamFields';
import { api, useLocale, usePack } from '@/lib/api';
import { useCheck } from '@/lib/check';
import { Banner, Body, Button, Card, Chip, ErrorText, Field, H2, Input, Loading, Muted, Row, Screen, colors, urgencyTone } from '@/lib/ui';

const CONFIDENCE: Record<string, { tone: 'ok' | 'soon' | 'ai'; text: string }> = {
  clear: { tone: 'ok', text: 'One cause stands out in this photo.' },
  split: { tone: 'soon', text: 'The top causes are close; the photo alone does not separate them.' },
  low: { tone: 'soon', text: 'The photo does not clearly match any condition. Treat these as weak hints and rely on your examination.' },
  unavailable: { tone: 'soon', text: 'AI analysis is not available right now. Red-flag checks still ran.' },
};

/** The analyzed photo(s), shown above the results for reference. Still only on this phone. */
function PhotoStrip({ uris }: { uris: string[] }) {
  if (!uris.length) return null;
  if (uris.length === 1) {
    return <Image source={{ uri: uris[0] }} style={{ width: '100%', aspectRatio: 4 / 3, borderRadius: 12 }} contentFit="cover" />;
  }
  return (
    <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8 }}>
      {uris.map((u) => (
        <Image key={u} source={{ uri: u }} style={{ width: 240, aspectRatio: 4 / 3, borderRadius: 12 }} contentFit="cover" />
      ))}
    </ScrollView>
  );
}

function Bar({ value }: { value: number }) {
  return (
    <View style={{ height: 8, backgroundColor: colors.border, borderRadius: 4, overflow: 'hidden' }}>
      <View style={{ width: `${Math.max(2, Math.round(value * 100))}%`, height: 8, backgroundColor: colors.ai }} />
    </View>
  );
}

function ResultCard({ r, rank, locale }: { r: ExplainedResult; rank: number; locale: string }) {
  return (
    <Card>
      <Row>
        <View style={{ flex: 1 }}>
          <Body bold>
            {rank}. {t(r.name, locale)}
          </Body>
        </View>
        <Body bold>{Math.round(r.probability * 100)}%</Body>
      </Row>
      <Bar value={r.probability} />
      <Muted>
        {r.likelihood} likelihood{r.emergency ? ' · can threaten sight, rule out urgently' : ''}
      </Muted>
      {r.visual_features && (
        <Body>
          <Body bold>What the AI looks for: </Body>
          {t(r.visual_features, locale)}
        </Body>
      )}
      {r.supports.map((s, i) => (
        <Body key={`s${i}`}>✓ {t(s, locale)}</Body>
      ))}
      {r.against.map((s, i) => (
        <Body key={`a${i}`}>✗ {t(s, locale)}</Body>
      ))}
    </Card>
  );
}

/** Lower-ranked conditions, folded by default. Tap a row to see its explanation. */
function OtherPossibilities({ items, start, locale }: { items: ExplainedResult[]; start: number; locale: string }) {
  const [open, setOpen] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  if (!items.length) return null;
  return (
    <Card>
      <Pressable onPress={() => setOpen(!open)} accessibilityRole="button" accessibilityState={{ expanded: open }}>
        <Row>
          <View style={{ flex: 1 }}>
            <Body bold>Other possibilities ({items.length})</Body>
          </View>
          <Muted>{open ? 'Hide ▴' : 'Show ▾'}</Muted>
        </Row>
      </Pressable>
      {open &&
        items.map((r, i) =>
          expanded === r.condition_id ? (
            <Pressable key={r.condition_id} onPress={() => setExpanded(null)}>
              <ResultCard r={r} rank={start + i} locale={locale} />
            </Pressable>
          ) : (
            <Pressable key={r.condition_id} onPress={() => setExpanded(r.condition_id)} style={{ gap: 4, paddingVertical: 4 }}>
              <Row>
                <View style={{ flex: 1 }}>
                  <Body>
                    {start + i}. {t(r.name, locale)}
                  </Body>
                </View>
                <Muted>{Math.round(r.probability * 100)}%</Muted>
              </Row>
              <Bar value={r.probability} />
            </Pressable>
          ),
        )}
    </Card>
  );
}

/** A few questions picked for this photo. Answers refine the explanation and red flags, not the AI ranking. */
function FollowUp({ locale }: { locale: string }) {
  const { pack } = usePack();
  const { result, answers, age, set } = useCheck();
  const [draft, setDraft] = useState<Record<string, unknown>>({});
  const [draftAge, setDraftAge] = useState('');
  const update = useMutation({
    mutationFn: () => {
      const merged = { ...answers, ...draft };
      const newAge = draftAge ? Number(draftAge) : age;
      return api.explain(result!.analysis_token, cleanAnswers(pack!, merged), newAge).then((r) => ({ r, merged, newAge }));
    },
    onSuccess: ({ r, merged, newAge }) => {
      set({ result: { ...result!, ...r }, answers: merged, age: newAge });
      setDraft({});
      setDraftAge('');
    },
  });

  if (!pack || !result || !result.follow_up.length) return null;
  const changed = Object.keys(draft).length > 0 || !!draftAge;
  return (
    <Card>
      <H2>Sharpen the explanation</H2>
      <Muted>
        {result.answered_questions === 0
          ? 'Based on the photo only so far. These questions matter most for this photo and switch on safety checks.'
          : 'A few more questions that matter for these results.'}
      </Muted>
      {result.follow_up.map((id) => {
        if (id === 'age') {
          return (
            <Field key={id} label="Age (years)">
              <Input value={draftAge} onChangeText={(v) => setDraftAge(v.replace(/[^0-9]/g, ''))} keyboardType="number-pad" maxLength={3} />
            </Field>
          );
        }
        const field = pack.exam_form.fields.find((f) => f.id === id);
        if (!field) return null;
        return (
          <Field key={id} label={t(field.label, locale)}>
            <FieldInput field={field} value={draft[id] ?? answers[id]} locale={locale} onChange={(v) => setDraft({ ...draft, [id]: v })} />
          </Field>
        );
      })}
      <ErrorText error={update.error} />
      <Button title="Update explanation" onPress={() => update.mutate()} loading={update.isPending} disabled={!changed} />
    </Card>
  );
}

export default function Result() {
  const router = useRouter();
  const locale = useLocale();
  const { result, reset, photos } = useCheck();
  const [confirmed, setConfirmed] = useState<string | null>(null);
  const [rating, setRating] = useState<string | null>(null);
  const [sent, setSent] = useState(false);

  if (!result) return <Loading />;
  const conf = CONFIDENCE[result.confidence];
  const poorPhotos = result.photos.filter((p) => !p.ok);

  async function send() {
    if (!confirmed) return;
    await api
      .confirm(result!.analysis_token, [{ condition_id: confirmed, side: null }], result!.suggested_urgency, rating)
      .catch(() => {});
    setSent(true);
  }

  return (
    <Screen>
      <PhotoStrip uris={photos.map((p) => p.uri)} />
      {photos.length > 1 && <Muted>{photos.length} photos analyzed together; the result below combines them.</Muted>}
      {result.red_flags.map((f) => (
        <Banner key={f.key} tone={urgencyTone(f.severity)}>
          <Body bold>Red flag</Body>
          <Body>{t(f.message, locale)}</Body>
        </Banner>
      ))}

      <Banner tone={conf.tone}>
        <Body bold>{result.label}</Body>
        <Body>{conf.text}</Body>
        <Muted>Suggested urgency: {result.suggested_urgency}</Muted>
      </Banner>

      {result.results.map((r, i) => (
        <ResultCard key={r.condition_id} r={r} rank={i + 1} locale={locale} />
      ))}
      <OtherPossibilities items={result.others ?? []} start={result.results.length + 1} locale={locale} />

      <FollowUp locale={locale} />
      {poorPhotos.length > 0 && (
        <Banner tone="soon">
          {poorPhotos.flatMap((p) => p.issues).map((i, k) => (
            <Body key={k}>{t(i.tip, locale)}</Body>
          ))}
        </Banner>
      )}

      {result.results.length > 0 && !sent && (
        <Card>
          <H2>Your diagnosis (optional)</H2>
          <Muted>Helps us measure how often the AI is right. Nothing about the patient is sent.</Muted>
          <Row>
            {result.results.map((r) => (
              <Chip key={r.condition_id} label={t(r.name, locale)} selected={confirmed === r.condition_id} onPress={() => setConfirmed(r.condition_id)} />
            ))}
          </Row>
          <Row>
            {[
              ['correct', 'AI was right'],
              ['wrong_cause', 'Wrong cause'],
              ['not_useful', 'Not useful'],
            ].map(([k, label]) => (
              <Chip key={k} label={label} selected={rating === k} onPress={() => setRating(k)} />
            ))}
          </Row>
          <Button title="Send" variant="secondary" onPress={send} disabled={!confirmed} />
        </Card>
      )}
      {sent && <Muted>Thanks, recorded anonymously.</Muted>}

      <Muted>
        Decision support only. The clinician is responsible for the diagnosis and plan.
        {result.model_version ? ` Model ${result.model_version}.` : ''}
      </Muted>
      <Button
        title="New check"
        onPress={() => {
          reset();
          router.dismissTo('/');
          router.push('/check/photo');
        }}
      />
      <Button title="Done" variant="secondary" onPress={() => (reset(), router.dismissTo('/'))} />
    </Screen>
  );
}
