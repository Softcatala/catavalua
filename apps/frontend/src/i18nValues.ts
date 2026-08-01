// Translates enum-like values stored in the DB (English, e.g. "male",
// "valencian", "catalan") into the active UI language. Falls back to the
// raw value when it doesn't match a known key, since models sometimes
// return free-form or oddly-cased text.
type Translator = (key: string, options: { defaultValue: string }) => string;

export function translateValue(
  t: Translator,
  category: 'gender' | 'dialect' | 'language' | 'origin',
  value: string | null | undefined,
): string {
  if (!value) return '';
  return t(`values.${category}.${value.toLowerCase()}`, { defaultValue: value });
}
