// Warming the policy is an optimization. A failed warmup must not end a
// conversation whose motor controller is already safely holding the arm.
export async function preloadRealtimeMolmo(sessionId, request = fetch) {
  try {
    const response = await request('/api/conversation/realtime/molmo/preload', {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-SO101-Conversation': 'operator-call' },
      body: JSON.stringify({ sessionId }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) return { ready: false, status: response.status,
      reason: payload.detail || `HTTP ${response.status}` };
    if (payload.ready !== true || payload.hardwareCommands !== false) {
      return { ready: false, status: response.status, reason: 'Invalid model readiness report.' };
    }
    return { ready: true, status: response.status, reason: null };
  } catch (error) {
    return { ready: false, status: null, reason: error.message };
  }
}
