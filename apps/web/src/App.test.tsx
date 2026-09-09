import { render, screen } from '@testing-library/react'
import { expect, test } from 'vitest'

import App from './App'

test('renders the simulation disclaimer', () => {
  render(<App />)
  expect(screen.getByText(/not a\s+real credit decisioning system/i)).toBeDefined()
})
