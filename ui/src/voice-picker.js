// All affordances share the existing conversation voice-selection boundary.
export class VoicePicker {
  constructor({ select, onSelect, now = () => performance.now() }) {
    Object.assign(this, { select, onSelect, now });
    this.voices = [];
    this.disabled = false;
    this.index = 0;
    this.wheelDelta = 0;
    this.wheelAt = 0;
    select.addEventListener('change', () => this.pick(select.selectedIndex));
    const wheel = (event) => {
      if (this.disabled || !event.deltaY) return;
      event.preventDefault();
      const time = this.now();
      if (time - this.wheelAt > 300) this.wheelDelta = 0;
      this.wheelAt = time;
      this.wheelDelta += event.deltaY * (event.deltaMode === 1 ? 16
        : event.deltaMode === 2 ? (globalThis.innerHeight || 800) : 1);
      if (Math.abs(this.wheelDelta) < 70) return;
      this.pick(this.index + Math.sign(this.wheelDelta));
      this.wheelDelta = 0;
    };
    select.addEventListener('wheel', wheel, { passive: false });
  }

  pick(index) {
    if (this.disabled || !this.voices.length) return;
    this.onSelect((index + this.voices.length) % this.voices.length);
  }

  render(voices, index, disabled) {
    const signature = voices.map(voice => `${voice.value}:${voice.name}`).join('|');
    if (this.signature !== signature) {
      this.select.replaceChildren(...voices.map(voice => {
        const option = this.select.ownerDocument.createElement('option');
        option.value = voice.value;
        option.textContent = voice.name;
        return option;
      }));
      this.signature = signature;
    }
    if (disabled !== this.disabled) this.wheelDelta = 0;
    Object.assign(this, { voices, index, disabled });
    this.select.selectedIndex = index;
    this.select.disabled = disabled;
  }
}
