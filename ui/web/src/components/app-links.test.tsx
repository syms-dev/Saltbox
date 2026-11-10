import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { OpenLinks, overallUpdate } from './app-links';

describe('overallUpdate', () => {
  it('reports an update when any container has one', () => {
    expect(overallUpdate(['current', 'update'])).toBe('update');
    expect(overallUpdate(['current', 'current'])).toBe('current');
    expect(overallUpdate(['current', 'unknown'])).toBe('unknown');
    expect(overallUpdate([])).toBe('unknown');
  });
});

describe('OpenLinks', () => {
  it('opens the app in a new tab', () => {
    render(<OpenLinks urls={['https://sonarr.thesyms.ca']} />);
    const link = screen.getByRole('link', { name: 'Open sonarr.thesyms.ca' });
    expect(link).toHaveAttribute('href', 'https://sonarr.thesyms.ca');
    expect(link).toHaveAttribute('target', '_blank');
  });

  it('renders nothing for apps without a web page', () => {
    const { container } = render(<OpenLinks urls={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
