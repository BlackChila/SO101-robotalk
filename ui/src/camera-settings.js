export class CameraSettingsToggle {
  constructor(button, panel, onToggle) {
    this.button = button;
    this.panel = panel;
    this.open = false;
    button.addEventListener('click', () => {
      if (button.hidden || button.disabled) return;
      this.open = !this.open;
      this.render(true);
      onToggle();
    });
  }

  render(available) {
    if (!available) this.open = false;
    this.button.hidden = !available;
    this.panel.hidden = !available || !this.open;
    this.button.setAttribute('aria-expanded', String(!this.panel.hidden));
  }
}

export class CameraBrightnessControls {
  constructor(panel, onApply, kind = 'brightness') {
    this.kind = kind;
    this.label = kind === 'exposure' ? 'Exposure' : 'Brightness';
    this.panel = panel;
    this.input = panel.querySelector('input');
    this.output = panel.querySelector('output');
    this.apply = panel.querySelector(`[data-${kind}-apply]`);
    this.reset = panel.querySelector(`[data-${kind}-reset]`);
    this.message = panel.querySelector(`[data-${kind}-message]`);
    this.role = null;
    this.control = null;
    this.dirty = false;
    this.disabled = true;
    this.input.addEventListener('input', () => {
      this.dirty = true;
      this.message.textContent = `${this.label} changed · apply to save.`;
      this.update();
    });
    this.reset.addEventListener('click', () => {
      if (this.disabled || !this.control) return;
      this.input.value = this.control.default;
      this.dirty = true;
      this.message.textContent = `Default ${this.label.toLowerCase()} selected · apply to save.`;
      this.update();
    });
    this.apply.addEventListener('click', () => {
      if (!this.apply.disabled) void onApply(this.role, Number(this.input.value), this);
    });
  }

  receive(control, role, applied = false) {
    if (role !== this.role || !control) this.dirty = false;
    this.role = role;
    this.control = control || null;
    if (control) {
      this.input.min = control.min;
      this.input.max = control.max;
      this.input.step = control.step;
      if (!this.dirty || applied) {
        this.input.value = control.value;
        this.dirty = false;
        this.message.textContent = applied ? `${this.label} saved · restored on each start.`
          : this.kind === 'exposure' ? 'Too bright? Reduce exposure. Brightness changes the black level.' : 'Adjust camera brightness manually.';
      }
    } else {
      this.message.textContent = `This camera has no available ${this.label.toLowerCase()} control.`;
    }
    if (this.kind === 'exposure') this.panel.hidden = !control;
    this.update();
  }

  render(disabled) {
    this.disabled = disabled || !this.control;
    this.update();
  }

  update() {
    this.input.disabled = this.disabled;
    this.output.textContent = this.control ? (this.kind === 'exposure' ? `${(Number(this.input.value) / 10).toFixed(1)} ms` : this.input.value) : '—';
    this.apply.disabled = this.disabled || !this.dirty;
    this.reset.disabled = this.disabled;
  }
}
