// Shared helpers used by every page.

function spinnerSvg(size) {
  return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" class="animate-spin text-[#E8002D]"><circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="2" stroke-opacity="0.15" /><path d="M12 2a10 10 0 0 1 10 10" stroke="currentColor" stroke-width="2" stroke-linecap="round" /></svg>`;
}

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
}

// Buttons with data-loading show a spinner and that text while their form submits.
document.addEventListener('submit', (e) => {
  const btn = e.target.querySelector('button[data-loading]');
  if (!btn) return;
  setTimeout(() => {
    btn.disabled = true;
    btn.innerHTML = spinnerSvg(16) + escapeHtml(btn.dataset.loading);
  });
});

// Coming back with the browser's back button should not show a stuck spinner.
window.addEventListener('pageshow', (e) => {
  if (e.persisted) location.reload();
});

// Six-digit code input: an invisible <input> captures typing, boxes show the digits.
document.querySelectorAll('[data-otp]').forEach((root) => {
  const input = root.querySelector('input');
  const boxes = root.querySelector('[data-otp-boxes]');

  function render() {
    const v = input.value;
    boxes.innerHTML = Array.from({ length: 6 }, (_, i) => {
      const filled = i < v.length;
      const content = v[i] || (i === v.length ? '<span class="w-[1px] h-5 bg-[#E8002D] animate-pulse rounded-full"></span>' : '');
      return `<div class="flex-1 h-12 flex items-center justify-center rounded-lg border font-mono text-lg text-[#F0F2F5] transition-colors duration-150 ${filled ? 'border-[#E8002D]/60 bg-[#E8002D]/5' : 'border-[rgba(255,255,255,0.08)] bg-[#1C2330]'}">${content}</div>`;
    }).join('');
  }

  input.addEventListener('input', () => {
    input.value = input.value.replace(/\D/g, '').slice(0, 6);
    render();
  });
  render();
});
