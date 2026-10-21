// Images are conversation input, not a base64 string inside function_call_output.
// Send each view separately to stay below WebRTC's per-message size limit.
export function sceneMessages(snapshot, callId) {
  const images = snapshot.images || [];
  const seen = new Set();
  for (const image of images) {
    if (!['overhead', 'wrist'].includes(image.camera) || seen.has(image.camera)
      || !/^data:image\/jpeg;base64,[A-Za-z0-9+/]+={0,2}$/.test(image.imageUrl)
      || image.imageUrl.length > 54_000 || !Number.isFinite(image.capturedAt)) {
      throw new Error('Invalid camera image for Realtime.');
    }
    seen.add(image.camera);
  }
  const metadata = { status: snapshot.status, unavailable: snapshot.unavailable || [],
    images: images.map(({ imageUrl, ...info }) => info) };
  return [
    { type: 'conversation.item.create', item: {
      type: 'function_call_output', call_id: callId, output: JSON.stringify(metadata),
    } },
    ...images.map(image => ({ type: 'conversation.item.create', item: {
      type: 'message', role: 'user', content: [
        { type: 'input_text', text: `Camera snapshot for look_at_scene (${callId}): ${image.camera}, captured ${new Date(image.capturedAt * 1000).toISOString()}. This is a single observation, not a new user instruction. ${image.camera === 'wrist' ? 'Upright Wrist view from the arm into its surroundings; consider relevant visible details alongside the overhead view.' : 'Overhead view of the workspace.'}` },
        { type: 'input_image', image_url: image.imageUrl },
      ],
    } })),
  ];
}
