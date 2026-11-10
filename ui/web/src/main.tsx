import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';

import { App } from './app';
import { FeedbackProvider } from './components/feedback';
import './theme.css';

const queryClient = new QueryClient({
  defaultOptions: { queries: { refetchOnWindowFocus: false, retry: false } },
});

const container = document.getElementById('root');
if (container === null) throw new Error('missing #root element');

createRoot(container).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <FeedbackProvider>
          <App />
        </FeedbackProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
