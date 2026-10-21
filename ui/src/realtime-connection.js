export function waitForRealtimeChannel(channel, peer, timeoutMs = 20_000) {
  return new Promise((resolve, reject) => {
    let timer;
    const finish = (error) => {
      clearTimeout(timer);
      channel.removeEventListener('open', opened);
      channel.removeEventListener('close', closed);
      channel.removeEventListener('error', closed);
      peer.removeEventListener('connectionstatechange', changed);
      error ? reject(error) : resolve();
    };
    const opened = () => finish();
    const closed = () => finish(new Error('ChatGPT Realtime-Datenkanal wurde nicht geöffnet.'));
    const changed = () => {
      if (['failed', 'closed'].includes(peer.connectionState)) closed();
    };
    if (channel.readyState === 'open') { resolve(); return; }
    if (channel.readyState === 'closed' || ['failed', 'closed'].includes(peer.connectionState)) {
      closed(); return;
    }
    channel.addEventListener('open', opened);
    channel.addEventListener('close', closed);
    channel.addEventListener('error', closed);
    peer.addEventListener('connectionstatechange', changed);
    timer = setTimeout(() => finish(new Error('ChatGPT Realtime-Verbindung hat das Zeitlimit überschritten.')), timeoutMs);
  });
}
