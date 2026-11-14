/**
 * Shiki theme built from the Skillporter palette.
 * Blue carries structure (keywords, keys), amber carries values that matter
 * (strings, numbers), ivory is plain text. No other hues are introduced.
 */
const ivory = '#F3F0E9';
const secondary = '#A6B0C0';
const muted = '#7C879B';
const blueInk = '#8AB4FF';
const blueSoft = '#B6CCF5';
const amber = '#F18A50';
const amberSoft = '#F6B58E';

/** @type {import('shiki').ThemeRegistration} */
export const skillporterTheme = {
  name: 'skillporter-midnight',
  type: 'dark',
  colors: {
    'editor.background': '#0B1425',
    'editor.foreground': ivory,
  },
  fg: ivory,
  bg: '#0B1425',
  settings: [
    { settings: { foreground: ivory, background: '#0B1425' } },
    { scope: ['comment', 'punctuation.definition.comment'], settings: { foreground: muted } },
    {
      scope: ['string', 'string.quoted', 'string.unquoted', 'punctuation.definition.string'],
      settings: { foreground: amberSoft },
    },
    {
      scope: ['constant.numeric', 'constant.language', 'constant.character.escape', 'constant.other'],
      settings: { foreground: amber },
    },
    {
      scope: ['keyword', 'storage', 'storage.type', 'keyword.operator.expression', 'keyword.control'],
      settings: { foreground: blueInk },
    },
    {
      scope: [
        'entity.name.tag',
        'support.type.property-name',
        'entity.name.tag.yaml',
        'meta.object-literal.key',
        'variable.other.property',
      ],
      settings: { foreground: blueSoft },
    },
    {
      scope: ['entity.name.function', 'support.function', 'entity.name.command', 'meta.function-call'],
      settings: { foreground: ivory },
    },
    {
      scope: ['variable', 'variable.other', 'variable.parameter'],
      settings: { foreground: ivory },
    },
    {
      scope: ['variable.other.normal.shell', 'variable.other.bracket.shell', 'punctuation.definition.variable'],
      settings: { foreground: blueSoft },
    },
    {
      scope: ['constant.other.option', 'variable.parameter.option', 'entity.other.attribute-name'],
      settings: { foreground: blueInk },
    },
    {
      scope: ['punctuation', 'meta.brace', 'keyword.operator', 'punctuation.separator'],
      settings: { foreground: secondary },
    },
    { scope: ['entity.name.type', 'support.class', 'support.type'], settings: { foreground: blueSoft } },
    { scope: ['markup.heading', 'markup.bold'], settings: { foreground: ivory, fontStyle: 'bold' } },
    { scope: ['markup.inline.raw', 'markup.raw'], settings: { foreground: amberSoft } },
  ],
};
