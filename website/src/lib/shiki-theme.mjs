/**
 * Shiki themes built from the Skillporter palette (light default + dark).
 * Blue carries structure (keywords, keys), amber carries values that matter
 * (strings, numbers), primary ink is plain text. No extra hues introduced.
 */
const ivory = '#F3F0E9';
const secondary = '#A6B0C0';
const muted = '#7C879B';
const blueInk = '#8AB4FF';
const blueSoft = '#B6CCF5';
const amber = '#F18A50';
const amberSoft = '#F6B58E';

const midnight = '#070D19';
const lightSecondary = '#3B4963';
const lightMuted = '#56657F';
const electric = '#155BE8';
const lightBlueKey = '#0F49BD';
const lightAmber = '#B94E14';
const lightAmberString = '#9A3E0C';

/** @type {import('shiki').ThemeRegistration} */
export const skillporterLightTheme = {
  name: 'skillporter-daylight',
  type: 'light',
  colors: {
    'editor.background': '#F6F8FC',
    'editor.foreground': midnight,
  },
  fg: midnight,
  bg: '#F6F8FC',
  settings: [
    { settings: { foreground: midnight, background: '#F6F8FC' } },
    { scope: ['comment', 'punctuation.definition.comment'], settings: { foreground: lightMuted } },
    {
      scope: ['string', 'string.quoted', 'string.unquoted', 'punctuation.definition.string'],
      settings: { foreground: lightAmberString },
    },
    {
      scope: ['constant.numeric', 'constant.language', 'constant.character.escape', 'constant.other'],
      settings: { foreground: lightAmber },
    },
    {
      scope: ['keyword', 'storage', 'storage.type', 'keyword.operator.expression', 'keyword.control'],
      settings: { foreground: electric },
    },
    {
      scope: [
        'entity.name.tag',
        'support.type.property-name',
        'entity.name.tag.yaml',
        'meta.object-literal.key',
        'variable.other.property',
      ],
      settings: { foreground: lightBlueKey },
    },
    {
      scope: ['entity.name.function', 'support.function', 'entity.name.command', 'meta.function-call'],
      settings: { foreground: midnight },
    },
    {
      scope: ['variable', 'variable.other', 'variable.parameter'],
      settings: { foreground: midnight },
    },
    {
      scope: ['variable.other.normal.shell', 'variable.other.bracket.shell', 'punctuation.definition.variable'],
      settings: { foreground: lightBlueKey },
    },
    {
      scope: ['constant.other.option', 'variable.parameter.option', 'entity.other.attribute-name'],
      settings: { foreground: electric },
    },
    {
      scope: ['punctuation', 'meta.brace', 'keyword.operator', 'punctuation.separator'],
      settings: { foreground: lightSecondary },
    },
    { scope: ['entity.name.type', 'support.class', 'support.type'], settings: { foreground: lightBlueKey } },
    { scope: ['markup.heading', 'markup.bold'], settings: { foreground: midnight, fontStyle: 'bold' } },
    { scope: ['markup.inline.raw', 'markup.raw'], settings: { foreground: lightAmberString } },
  ],
};

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
