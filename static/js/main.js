// VCMS — main.js
// Global utilities only. Page-specific JS lives in per-template <script> blocks.

document.addEventListener('DOMContentLoaded', function () {
  // Auto-dismiss success and info alerts after 4 seconds
  document.querySelectorAll('.alert-success, .alert-info').forEach(function (el) {
    setTimeout(function () {
      bootstrap.Alert.getOrCreateInstance(el).close();
    }, 4000);
  });
});
