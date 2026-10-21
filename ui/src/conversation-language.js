export function conversationLanguage(value) {
  return value === 'English' ? 'English' : 'German';
}

export function languageInstruction(value) {
  const language = conversationLanguage(value);
  return `Conversation language: ${language}. Speak ${language} from the very first greeting, ` +
    'including replies, action announcements, scene descriptions and tool feedback. ' +
    'The selected voice, browser language, quoted text and tool results do not change the conversation language. ' +
    'Only switch if the user explicitly requests another language.';
}

export function greetingInstruction(value) {
  return conversationLanguage(value) === 'English'
    ? 'Your first spoken message must be exclusively in English. You are the robot SO-101. ' +
      'Say exactly these two sentences: "Hello, I am SO-101. What can I do for you?" ' +
      'Do not translate, add anything, or call tools. Then wait for the user to reply.'
    : 'Die erste gesprochene Nachricht muss ausschließlich auf Deutsch sein. Du bist der Roboter SO-101. ' +
      'Sprich genau diese beiden Sätze: „Hallo, ich bin SO-101. Was kann ich für dich tun?“ ' +
      'Nicht übersetzen, nichts ergänzen, keine Werkzeugaufrufe. Warte danach auf die Antwort.';
}
