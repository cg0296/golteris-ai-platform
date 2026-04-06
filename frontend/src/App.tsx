/**
 * App.tsx — Root component for the Golteris broker console.
 *
 * This is a placeholder that confirms the frontend is deployed and working.
 * It will be replaced by the real dashboard layout when issue #17
 * (Build broker home dashboard) is implemented.
 */

function App() {
  return (
    <div style={{
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
      maxWidth: '600px',
      margin: '80px auto',
      padding: '0 20px',
      color: '#1a1a2e',
    }}>
      <h1 style={{ fontSize: '28px', marginBottom: '8px' }}>Golteris</h1>
      <p style={{ color: '#666', marginBottom: '32px' }}>
        Operational AI Workflow Platform
      </p>
      <div style={{
        background: '#f0fdf4',
        border: '1px solid #bbf7d0',
        borderRadius: '8px',
        padding: '16px 20px',
        marginBottom: '16px',
      }}>
        <strong>Status:</strong> Deployed and running
      </div>
      <p style={{ fontSize: '14px', color: '#999' }}>
        The broker dashboard will be built in issue #17.
      </p>
    </div>
  )
}

export default App
