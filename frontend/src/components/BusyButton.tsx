import type { ButtonHTMLAttributes } from 'react'

export const Spinner = () => <span className="spinner" aria-hidden="true" />

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  busy: boolean
  busyLabel: string
}

/** A button that, while `busy`, is disabled and shows a spinner with `busyLabel`. */
export default function BusyButton({ busy, busyLabel, children, disabled, ...rest }: Props) {
  return (
    <button type="button" {...rest} disabled={busy || disabled} aria-busy={busy}>
      {busy ? <><Spinner />{busyLabel}</> : children}
    </button>
  )
}
