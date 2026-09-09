import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { expect, test, vi } from 'vitest'

import App from './App'

test('states plainly that this is a simulation', () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response('[]', { headers: { 'Content-Type': 'application/json' } }),
  )
  render(
    <MemoryRouter>
      <App />
    </MemoryRouter>,
  )
  expect(screen.getByText(/not a real decisioning system/i)).toBeDefined()
})
