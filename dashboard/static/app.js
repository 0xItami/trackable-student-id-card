(() => {
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('/sw.js', {scope: '/'}).catch(error => {
        console.warn('Offline presentation support could not start.', error);
      });
    });
  }

  function showConnectionState() {
    document.documentElement.dataset.connection = navigator.onLine ? 'online' : 'offline';
    let banner = document.getElementById('offline-banner');
    if (!navigator.onLine && !banner) {
      banner = document.createElement('div');
      banner.id = 'offline-banner';
      banner.className = 'offline-banner';
      banner.textContent = 'Internet is unavailable — saved presentation data remains usable.';
      document.body.appendChild(banner);
    } else if (navigator.onLine && banner) {
      banner.remove();
    }
  }

  window.addEventListener('online', showConnectionState);
  window.addEventListener('offline', showConnectionState);
  window.addEventListener('DOMContentLoaded', showConnectionState);
})();
