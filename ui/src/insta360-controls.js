export class Insta360Controls {
  constructor(panel, onApply) {
    this.panel = panel;
    this.inputs = [...panel.querySelectorAll('input[data-axis]')];
    this.apply = panel.querySelector('[data-apply]');
    this.reset = panel.querySelector('[data-reset]');
    this.message = panel.querySelector('[data-message]');
    this.view = null;
    this.dirty = false;
    this.disabled = true;
    this.inputs.forEach((input) => input.addEventListener('input', () => {
      this.dirty = true;
      this.message.textContent = 'Ausschnitt geändert · mit „Übernehmen“ im Livebild prüfen.';
      this.update();
    }));
    this.reset.addEventListener('click', () => {
      if (this.disabled || !this.view?.defaults) return;
      this.setValues(this.view.defaults);
      this.dirty = true;
      this.message.textContent = 'Standardwerte gewählt · mit „Übernehmen“ anwenden.';
      this.update();
    });
    this.apply.addEventListener('click', () => {
      if (this.apply.disabled) return;
      void onApply(Object.fromEntries(this.inputs.map((input) => [input.dataset.axis, Number(input.value)])));
    });
  }

  setValues(view) {
    this.inputs.forEach((input) => { input.value = view[input.dataset.axis] ?? (input.dataset.axis === 'zoom' ? 1 : 0); });
  }

  receive(view, applied = false) {
    const wasAvailable = Boolean(this.view);
    this.view = view || null;
    if (!this.view) this.dirty = false;
    if (this.view && (applied || !this.dirty || !wasAvailable)) {
      this.setValues(this.view);
      this.dirty = false;
      this.message.textContent = applied ? 'Ausschnitt gespeichert · bei jedem Start wieder verwendet.'
        : 'Ausrichtung und Zoom einstellen; anschließend übernehmen.';
    }
    this.update();
  }

  render(available, disabled) {
    this.panel.hidden = !available || !this.view;
    this.disabled = disabled || this.panel.hidden;
    this.update();
  }

  update() {
    this.inputs.forEach((input) => {
      input.disabled = this.disabled;
      this.panel.querySelector(`[data-value="${input.dataset.axis}"]`).textContent = input.dataset.axis === 'zoom'
        ? `${Number(input.value).toFixed(2).replace(/\.?0+$/, '')}×` : `${input.value}°`;
    });
    this.apply.disabled = this.disabled || !this.dirty;
    this.reset.disabled = this.disabled;
  }
}
