/**
 * SIMETRI - Frontend JavaScript
 * Theme switcher, modal management, and toast notifications.
 */

// Theme Management (Dark / Light)
function initTheme() {
  const storedTheme = localStorage.getItem('simetri-theme');
  const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  
  if (storedTheme === 'dark' || (!storedTheme && prefersDark)) {
    document.documentElement.classList.add('dark');
  } else {
    document.documentElement.classList.remove('dark');
  }
}

function toggleTheme() {
  const isDark = document.documentElement.classList.toggle('dark');
  localStorage.setItem('simetri-theme', isDark ? 'dark' : 'light');
}

// Modal Management
function openModal(htmlContent) {
  const container = document.getElementById('modal-container');
  if (container) {
    container.innerHTML = htmlContent;
    document.body.classList.add('overflow-hidden');
  }
}

function closeModal() {
  const container = document.getElementById('modal-container');
  if (container) {
    container.innerHTML = '';
    document.body.classList.remove('overflow-hidden');
  }
}

// Toast Notifications
function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container');
  if (!container) return;

  const bgColors = {
    success: 'bg-emerald-600 text-white',
    error: 'bg-rose-600 text-white',
    warning: 'bg-amber-600 text-white',
    info: 'bg-indigo-600 text-white',
  };

  const toast = document.createElement('div');
  toast.className = `toast-item flex items-center gap-3 px-4 py-3 rounded-xl shadow-xl text-sm font-medium ${bgColors[type] || bgColors.info}`;
  toast.innerHTML = `
    <span>${message}</span>
    <button onclick="this.parentElement.remove()" class="ml-auto opacity-70 hover:opacity-100">&times;</button>
  `;

  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transition = 'opacity 0.3s ease';
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

// Listen to htmx events
document.addEventListener('DOMContentLoaded', () => {
  initTheme();

  // Close modal when pressing Escape
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      closeModal();
    }
  });

  // Listen to custom HX-Trigger events
  document.body.addEventListener('refreshTimeline', () => {
    closeModal();
    showToast('Data kronologi berhasil diperbarui', 'success');
  });

  document.body.addEventListener('refreshSurat', () => {
    closeModal();
    showToast('Data arsip surat & lampiran berhasil disimpan', 'success');
  });

  document.body.addEventListener('refreshAgenda', (e) => {
    closeModal();
    const message = (e.detail && e.detail.message) ? e.detail.message : 'Data agenda kegiatan berhasil disimpan';
    showToast(message, 'success');
    if (window.location.pathname.startsWith('/agenda')) {
      const targetUrl = (e.detail && e.detail.url) ? e.detail.url : window.location.href;
      setTimeout(() => {
        window.location.href = targetUrl;
      }, 400);
    }
  });

  document.body.addEventListener('showToast', (e) => {
    const detail = e.detail || {};
    showToast(detail.message || 'Berhasil', detail.type || 'info');
  });
});
