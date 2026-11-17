import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'

import App from './App'
import { reportClientError } from './api'
import './styles.css'

window.addEventListener('error', (e) => reportClientError(e.message, e.error?.stack))
window.addEventListener('unhandledrejection', (e) => reportClientError(String(e.reason), e.reason?.stack))

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
)
