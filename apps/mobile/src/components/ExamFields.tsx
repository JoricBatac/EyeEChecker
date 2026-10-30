import { isVisible, t, type FormField, type Pack } from '@scanassist/shared';

import { Chip, Field, Input, Muted, Row } from '@/lib/ui';

export type Answers = Record<string, unknown>;
const VA_SHORTCUTS = ['6/6', '6/9', '6/12', '6/18', '6/24', '6/36', '6/60', 'CF', 'HM', 'LP', 'NLP'];

export function FieldInput({ field, value, onChange, locale }: { field: FormField; value: unknown; onChange: (v: unknown) => void; locale: string }) {
  switch (field.type) {
    case 'single':
      return (
        <Row>
          {field.options.map((o) => (
            <Chip key={o.value} label={t(o.label, locale)} selected={value === o.value} onPress={() => onChange(value === o.value ? null : o.value)} />
          ))}
        </Row>
      );
    case 'multi': {
      const list = (value as string[] | undefined) ?? [];
      return (
        <Row>
          {field.options.map((o) => (
            <Chip
              key={o.value}
              label={t(o.label, locale)}
              selected={list.includes(o.value)}
              onPress={() => onChange(list.includes(o.value) ? list.filter((v) => v !== o.value) : [...list, o.value])}
            />
          ))}
        </Row>
      );
    }
    case 'boolean':
      return (
        <Row>
          <Chip label={locale === 'fil' ? 'Oo' : 'Yes'} selected={value === true} onPress={() => onChange(value === true ? null : true)} />
          <Chip label={locale === 'fil' ? 'Hindi' : 'No'} selected={value === false} onPress={() => onChange(value === false ? null : false)} />
        </Row>
      );
    case 'visual_acuity':
      return (
        <Row>
          {VA_SHORTCUTS.map((v) => (
            <Chip key={v} label={v} selected={value === v} onPress={() => onChange(value === v ? null : v)} />
          ))}
        </Row>
      );
    case 'number':
      return <Input value={value == null ? '' : String(value)} keyboardType="decimal-pad" onChangeText={(v) => onChange(v === '' ? null : Number(v))} />;
    default:
      return null;
  }
}

/** Optional exam questions from the pack. Free-text fields are left out of the quick flow. */
export function ExamFields({ pack, answers, onChange, locale }: { pack: Pack; answers: Answers; onChange: (a: Answers) => void; locale: string }) {
  const fields = pack.exam_form.fields.filter((f) => !f.free_text && isVisible(f, answers));
  return (
    <>
      <Muted>All optional. Answers improve the explanation and switch on safety checks.</Muted>
      {fields.map((f) => (
        <Field key={f.id} label={t(f.label, locale)}>
          <FieldInput field={f} value={answers[f.id]} locale={locale} onChange={(v) => onChange({ ...answers, [f.id]: v })} />
        </Field>
      ))}
    </>
  );
}

/** Drop unanswered and hidden fields before sending. */
export function cleanAnswers(pack: Pack, answers: Answers): Answers {
  return Object.fromEntries(
    Object.entries(answers).filter(([k, v]) => {
      const f = pack.exam_form.fields.find((x) => x.id === k);
      return f && !f.free_text && isVisible(f, answers) && v != null && v !== '' && !(Array.isArray(v) && !v.length);
    }),
  );
}
