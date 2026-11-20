import { describe, expect, it } from 'vitest'
import { SerialQueue, flowIn } from './serialQueue'

describe('SerialQueue', () => {
  it('runs one request at a time and builds each from the state the previous one left', async () => {
    const queue = new SerialQueue<number>()
    queue.current = 1
    const log: string[] = []
    let release!: () => void
    const slow = new Promise<void>((r) => (release = r))
    queue.push((v) => `first@${v}`, async (r) => { log.push(`start ${r}`); await slow; queue.current = 2; log.push(`end ${r}`) })
    const second = queue.push((v) => `second@${v}`, async (r) => { log.push(`start ${r}`) })
    await Promise.resolve()
    expect(log).toEqual(['start first@1'])
    release()
    await second
    expect(log).toEqual(['start first@1', 'end first@1', 'start second@2'])
  })

  it('skips a request whose build returns null', async () => {
    const queue = new SerialQueue<number>()
    const ran: number[] = []
    await queue.push(() => null, async () => { ran.push(1) })
    await queue.push(() => 2, async (r) => { ran.push(r) })
    expect(ran).toEqual([2])
  })
})

describe('flowIn', () => {
  const view = { flows: [{ stream_id: 1, version: 3 }, { stream_id: 2, version: 7 }] }
  it('finds the flow by stream id', () => expect(flowIn(view, 2)).toEqual({ stream_id: 2, version: 7 }))
  it('is null when the flow is gone', () => expect(flowIn(view, 9)).toBeNull())
  it('is null when there is no view yet', () => expect(flowIn(null, 1)).toBeNull())
})
