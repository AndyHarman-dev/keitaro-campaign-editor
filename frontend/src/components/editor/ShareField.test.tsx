import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import ShareField from './ShareField'

function setup(share = 34, disabled = false) {
  const onCommit = vi.fn()
  render(<><ShareField offerId={3749} share={share} disabled={disabled} onCommit={onCommit} /><button>elsewhere</button></>)
  return { onCommit, user: userEvent.setup() }
}

async function edit(user: ReturnType<typeof userEvent.setup>, value: string) {
  await user.click(screen.getByRole('button', { name: 'Edit share of offer 3749, currently 34 percent' }))
  const input = screen.getByLabelText('Share for offer 3749')
  expect(input).toHaveFocus()
  await user.clear(input)
  if (value) await user.type(input, value)
  return input
}

describe('ShareField (vision §5: Enter or blur applies, Escape cancels)', () => {
  it('applies on Enter', async () => {
    const { onCommit, user } = setup()
    await edit(user, '50{Enter}')
    expect(onCommit).toHaveBeenCalledExactlyOnceWith(50)
    expect(screen.queryByLabelText('Share for offer 3749')).not.toBeInTheDocument()
  })

  it('applies when the field loses focus', async () => {
    const { onCommit, user } = setup()
    await edit(user, '20')
    await user.click(screen.getByRole('button', { name: 'elsewhere' }))
    expect(onCommit).toHaveBeenCalledExactlyOnceWith(20)
  })

  it('cancels on Escape', async () => {
    const { onCommit, user } = setup()
    await edit(user, '20{Escape}')
    expect(onCommit).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: /currently 34 percent/ })).toBeInTheDocument()
  })

  it('does nothing when the value is unchanged', async () => {
    const { onCommit, user } = setup()
    await edit(user, '34')
    await user.click(screen.getByRole('button', { name: 'elsewhere' }))
    expect(onCommit).not.toHaveBeenCalled()
  })

  it('treats an empty field as unchanged', async () => {
    const { onCommit, user } = setup()
    await edit(user, '{Enter}')
    expect(onCommit).not.toHaveBeenCalled()
  })

  it('clamps to 0..100', async () => {
    const { onCommit, user } = setup()
    await edit(user, '150{Enter}')
    expect(onCommit).toHaveBeenCalledExactlyOnceWith(100)
  })

  it('cannot be edited while the row is removed', () => {
    setup(0, true)
    expect(screen.getByRole('button', { name: /Edit share of offer 3749/ })).toBeDisabled()
  })
})
