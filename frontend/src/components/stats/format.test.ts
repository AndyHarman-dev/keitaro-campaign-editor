import { describe, expect, it } from 'vitest'
import {
  cellLines, convLabel, deltaLabel, direction, money, noClicksLabel, observedLabel, pendingLabel, percent,
  periodLabel, sparkline, totalsLabel, trendAria, type Cell, type Trend,
} from './format'

const cell = (over: Partial<Cell> = {}): Cell => ({
  clicks: 1010, leads: 9, sales: 41, rejected: 3, conversions: 50, revenue: '171.7000', epc: '0.1700',
  cr: 0.0496, pending: 9 / 53, split: 0.42, ...over,
})

const week = (conversions: number, epc: string) => ({ clicks: 2000, conversions, epc })
const trend = (over: Partial<Trend> = {}): Trend => ({
  verdict: 'within_noise', daily_epc: [], older: week(80, '0.2400'), newer: week(72, '0.2000'),
  change: -0.1667, band: 0.3217, ...over,
})

describe('numbers', () => {
  it('formats money with the currency, two decimals, and a dash for none', () => {
    expect(money('0.1650', '$')).toBe('$0.17')
    expect(money('12', '€')).toBe('€12.00')
    expect(money(null, '$')).toBe('—')
  })

  it('formats ratios as percent to one decimal', () => {
    expect(percent(0.0525)).toBe('5.3%')
    expect(percent(0)).toBe('0.0%')
    expect(percent(null)).toBe('—')
  })

  it('names periods', () => {
    expect(periodLabel('today')).toBe('Today')
    expect(periodLabel('14')).toBe('14 days')
    expect(noClicksLabel('today')).toBe('No clicks today')
    expect(noClicksLabel('7')).toBe('No clicks in 7 days')
  })
})

describe('stats cell', () => {
  it('leads with EPC, then clicks and CR', () => {
    expect(cellLines(cell(), '$')).toEqual({ primary: 'EPC $0.17', secondary: '1,010 clicks · CR 5.0%' })
  })

  it('says how much is still pending, with the Today wording', () => {
    expect(pendingLabel(cell(), '7')).toBe('17% still pending')
    expect(pendingLabel(cell({ pending: 0.9 }), 'today')).toBe('today: mostly pending (90% still pending)')
    expect(pendingLabel(cell({ pending: null }), '7')).toBe('')
    expect(pendingLabel(cell({ pending: 0 }), 'today')).toBe('')
    expect(pendingLabel(cell({ pending: 0.004 }), '7')).toBe('')
    expect(pendingLabel(cell({ pending: 0.005 }), '7')).toBe('1% still pending')
  })

  it('shows the observed split, but not for flow totals', () => {
    expect(observedLabel(cell())).toBe("42% of this flow's clicks went here")
    expect(observedLabel(cell({ split: null }))).toBe('')
  })

  it('sums up a flow on one line', () => {
    expect(totalsLabel(cell({ clicks: 12345 }), '30', '$')).toBe('30 days: 12,345 clicks · CR 5.0% · EPC $0.17')
    expect(totalsLabel(cell(), 'today', '$')).toMatch(/^Today: /)
  })
})

describe('trend', () => {
  it('reads a real change with its sign', () => {
    expect(deltaLabel(trend({ verdict: 'up', change: 0.42 }))).toBe('+42%')
    expect(deltaLabel(trend({ verdict: 'down', change: -0.44 }))).toBe('−44%')
    expect(direction(trend({ verdict: 'down' }))).toBe('down')
  })

  it('reads a change smaller than the band as within noise, with counts and band', () => {
    const t = trend()
    expect(deltaLabel(t)).toBe('within noise')
    expect(direction(t)).toBe('noise')
    expect(convLabel(t)).toBe('80 → 72 conv. (−17%, band ±32%)')
    expect(convLabel(trend({ verdict: 'up', change: 0.42, band: 0.2 }))).toBe('80 → 72 conv.')
  })

  it('says nothing for thin weeks', () => {
    const thin = trend({ verdict: 'not_enough_traffic', change: null, band: null })
    expect(direction(thin)).toBeNull()
    expect(deltaLabel(thin)).toBe('')
    expect(convLabel(thin)).toBe('')
    expect(trendAria(thin, '$')).toBe('Trend: not enough traffic')
  })

  it('describes the trend for screen readers', () => {
    expect(trendAria(trend(), '$')).toBe(
      'EPC days 3 to 9 ago $0.20 versus $0.24 the week before, on 72 versus 80 conversions: change −17% is within noise')
    expect(trendAria(trend({ verdict: 'up', change: 0.42 }), '$')).toMatch(/: up 42%$/)
  })
})

describe('sparkline', () => {
  it('scales 14 days into the box and draws the last days as a lighter tail', () => {
    const daily = Array.from({ length: 14 }, (_, i) => String(i))
    const { main, tail } = sparkline(daily)
    expect(main.split(' ')).toHaveLength(12)
    expect(main.startsWith('3.0,23.0')).toBe(true)
    expect(tail).toBe('69.0,6.1 75.0,4.5 81.0,3.0')
  })

  it('skips days without clicks and copes with a flat or empty series', () => {
    expect(sparkline([null, '1', '1']).main).toBe('9.0,23.0 15.0,23.0')
    expect(sparkline(Array(14).fill(null))).toEqual({ main: '', tail: '' })
  })
})
