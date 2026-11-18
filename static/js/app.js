/* Library Management System - small UI helpers (no libraries needed). */
(function () {
  'use strict';

  var body = document.body;

  /* ----- Mobile sidebar ----- */
  document.querySelectorAll('[data-sidebar-toggle]').forEach(function (btn) {
    btn.addEventListener('click', function () { body.classList.toggle('sidebar-open'); });
  });
  document.querySelectorAll('[data-sidebar-close]').forEach(function (el) {
    el.addEventListener('click', function () { body.classList.remove('sidebar-open'); });
  });

  /* ----- Toast notifications: auto-dismiss + close button ----- */
  document.querySelectorAll('.toast').forEach(function (toast) {
    function dismiss() {
      toast.classList.add('hide');
      setTimeout(function () { toast.remove(); }, 300);
    }
    var close = toast.querySelector('.toast-close');
    if (close) { close.addEventListener('click', dismiss); }
    setTimeout(dismiss, toast.classList.contains('toast-error') ? 9000 : 5000);
  });

  /* ----- Confirmation before destructive actions -----
     Any <form data-confirm="message"> asks first. */
  var dialog = document.getElementById('confirm-dialog');
  var pendingForm = null;

  function submitConfirmed(form) {
    form.dataset.confirmed = '1';
    form.submit();
  }

  document.querySelectorAll('form[data-confirm]').forEach(function (form) {
    form.addEventListener('submit', function (event) {
      if (form.dataset.confirmed === '1') { return; }
      event.preventDefault();
      if (dialog && typeof dialog.showModal === 'function') {
        pendingForm = form;
        dialog.querySelector('[data-confirm-message]').textContent = form.dataset.confirm;
        dialog.showModal();
      } else if (window.confirm(form.dataset.confirm)) {
        submitConfirmed(form);
      }
    });
  });

  if (dialog) {
    var ok = dialog.querySelector('[data-confirm-ok]');
    var cancel = dialog.querySelector('[data-confirm-cancel]');
    if (ok) {
      ok.addEventListener('click', function () {
        dialog.close();
        if (pendingForm) { submitConfirmed(pendingForm); }
        pendingForm = null;
      });
    }
    if (cancel) {
      cancel.addEventListener('click', function () { dialog.close(); pendingForm = null; });
    }
    dialog.addEventListener('cancel', function () { pendingForm = null; });
  }

  /* ----- Filters that apply as soon as a dropdown changes ----- */
  document.querySelectorAll('select[data-autosubmit]').forEach(function (select) {
    select.addEventListener('change', function () { select.form.submit(); });
  });

  /* ----- Stop accidental double submits on add/edit/issue forms ----- */
  document.querySelectorAll('form[data-once]').forEach(function (form) {
    form.addEventListener('submit', function () {
      var btn = form.querySelector('button[type="submit"]');
      if (btn) { setTimeout(function () { btn.disabled = true; }, 0); }
    });
  });
})();
