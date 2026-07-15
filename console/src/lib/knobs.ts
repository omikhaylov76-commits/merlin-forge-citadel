// Реестр 23 крутилок движка Пифагора (эталон @b75bd17, сверено constructor-knobs.md / KNOB_SPECS).
// Полка: basic = под стиль; expert = тонкая механика (за экспертным режимом). danger ⚠ = вне честно
// оттестированных чисел → протухает OOS-паспорт. Значения etalon = «Малыш Мерлин» (клонируй-не-редактируй).
export type KnobValue = number | boolean | string
export type Knob = {
  key: string
  label: string
  type: 'number' | 'toggle' | 'select'
  etalon: KnobValue
  shelf: 'basic' | 'expert'
  danger?: boolean
  min?: number
  max?: number
  step?: number
  options?: string[]
  hint?: string
}
export type KnobCategory = { title: string; note?: string; knobs: Knob[] }

export const KNOB_CATEGORIES: KnobCategory[] = [
  {
    title: '1 · Риск',
    knobs: [
      { key: 'RISK_PCT_PER_LEG', label: 'Риск на ногу, %', type: 'number', etalon: 1.3, shelf: 'basic', min: 0.5, max: 10, step: 0.1 },
      { key: 'RISK_PCT_ALARM', label: 'Риск на ногу в тревоге, %', type: 'number', etalon: 0.65, shelf: 'expert', min: 0.1, max: 10, step: 0.05, hint: '≤ риск на ногу' },
      { key: 'ALARM_DD', label: 'Порог тревоги (просадка)', type: 'number', etalon: 0.4, shelf: 'basic', min: 0, max: 1, step: 0.01 },
      { key: 'KILLSWITCH_DD', label: 'Аварийный стоп (просадка)', type: 'number', etalon: 0.5, shelf: 'basic', min: 0, max: 1, step: 0.01, hint: 'тревога < стоп < 1' },
      { key: 'CONCURRENCY_CAP', label: 'Макс. одновременных позиций', type: 'number', etalon: 8, shelf: 'basic', min: 1, max: 16, step: 1 },
      { key: 'MAX_LEVERAGE', label: 'Макс. плечо', type: 'number', etalon: 5, shelf: 'basic', min: 1, max: 5, step: 1 },
    ],
  },
  {
    title: '2 · Капитал',
    knobs: [
      { key: 'WORKING_START', label: 'Рабочий капитал на старте', type: 'number', etalon: 10000, shelf: 'basic', min: 1, step: 100 },
      { key: 'CUSHION_START', label: 'Подушка на старте', type: 'number', etalon: 10000, shelf: 'basic', min: 0, step: 100 },
      { key: 'REFINANCE_SPLIT', label: 'Доля реинвеста', type: 'number', etalon: 0.5, shelf: 'basic', min: 0, max: 1, step: 0.05 },
    ],
  },
  {
    title: '3 · Исполнение / ноги',
    note: 'тонкая механика входов и бегунка',
    knobs: [
      { key: 'STOP_FIB', label: 'Уровень стопа (Fib)', type: 'number', etalon: 1.0, shelf: 'basic', danger: true, min: 0.5, max: 1.5, step: 0.05 },
      { key: 'SL_TRIGGER_BY', label: 'Стоп срабатывает по цене', type: 'select', etalon: 'LastPrice', shelf: 'expert', options: ['LastPrice', 'MarkPrice', 'IndexPrice'] },
      { key: 'REANCHOR_AFTER_SCALP', label: 'Пере-якорь после скальпа', type: 'toggle', etalon: false, shelf: 'expert' },
      { key: 'RUNNER_TP_HOLD', label: 'Держать бегунок (без раннего TP)', type: 'toggle', etalon: false, shelf: 'expert' },
      { key: 'LEG2_EXT', label: 'Цель бегунка (ext)', type: 'number', etalon: 1.0, shelf: 'expert', danger: true, min: 0, max: 3, step: 0.05 },
      { key: 'DOUBLE_DIP_ENABLED', label: 'Двойной заход', type: 'toggle', etalon: false, shelf: 'expert' },
      { key: 'DOUBLE_DIP_TOL', label: 'Допуск двойного захода, %', type: 'number', etalon: 0.04, shelf: 'expert', danger: true, min: 0, max: 0.1, step: 0.005 },
      { key: 'TRAIL_ENABLED', label: 'Трейлинг-стоп бегунка', type: 'toggle', etalon: false, shelf: 'expert' },
      { key: 'TRAIL_R', label: 'Ширина трейла (R)', type: 'number', etalon: 0.4, shelf: 'expert', danger: true, min: 0.1, max: 3, step: 0.1 },
    ],
  },
  {
    title: '4 · Режимы',
    knobs: [
      { key: 'SHORTS_ENABLED', label: 'Разрешить шорты', type: 'toggle', etalon: false, shelf: 'basic' },
      { key: 'EMA_FILTER_ENABLED', label: 'Фильтр по EMA200', type: 'toggle', etalon: false, shelf: 'basic' },
    ],
  },
  {
    title: '5 · Служебные / старт',
    note: 'рантайм-управление ботом',
    knobs: [
      { key: 'PAUSE_ENABLED', label: 'Авария: пауза', type: 'toggle', etalon: false, shelf: 'expert' },
      { key: 'WARM_ON_START', label: 'Тёплый старт (подхват сетапов)', type: 'toggle', etalon: false, shelf: 'expert' },
      { key: 'WARM_MAX_AGE_BARS', label: 'Окно свежести (бары)', type: 'number', etalon: 72, shelf: 'expert', min: 1, max: 500, step: 1 },
    ],
  },
]

export const ALL_KNOBS: Knob[] = KNOB_CATEGORIES.flatMap((c) => c.knobs)
export const ETALON: Record<string, KnobValue> = Object.fromEntries(
  ALL_KNOBS.map((k) => [k.key, k.etalon]),
)
