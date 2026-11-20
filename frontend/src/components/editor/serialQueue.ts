/** Runs requests one at a time. Each is built only when its turn comes, from `current`
 * (the latest state the previous requests left behind); a build that returns null is skipped. */
export class SerialQueue<S> {
  current: S | null = null
  private tail: Promise<void> = Promise.resolve()

  push<R>(build: (current: S | null) => R | null, run: (request: R) => Promise<void>): Promise<void> {
    this.tail = this.tail.then(() => {
      const request = build(this.current)
      return request === null ? undefined : run(request)
    })
    return this.tail
  }
}

/** The flow with `streamId` in `view`, or null when there is no view or the flow is gone. */
export function flowIn<F extends { stream_id: number }>(view: { flows: F[] } | null, streamId: number): F | null {
  return view?.flows.find((f) => f.stream_id === streamId) ?? null
}
