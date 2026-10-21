export function molmoRunStopState(task, pending = false) {
  const active = task?.model === 'molmoact2' && ['loading', 'running', 'stopping'].includes(task.state);
  const stopping = pending || (active && task.state === 'stopping');
  return { disabled: !active || stopping,
    label: stopping ? 'Model Run wird gestoppt …' : 'Model Run stoppen' };
}

export function keepMolmoForConversation(mode, status) {
  return ['realtime', 'piper', 'local'].includes(mode) && (status.modelSession === 'molmoact2' ||
    (status.taskRun?.model === 'molmoact2' && ['loading', 'running', 'stopping'].includes(status.taskRun.state)));
}
