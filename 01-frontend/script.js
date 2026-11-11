/**
 * Upload Your Resume — interaction layer.
 *
 * Nothing here is required for the page to look right; it implements the
 * "加分项" items from the brief: click-to-upload, drag highlight, file-name
 * display, and defensive validation with an inline message instead of an
 * alert(). All state lives in one function so there is a single source of truth.
 */

(function () {
  'use strict';

  var MAX_BYTES = 5 * 1024 * 1024; // 5MB, per "File size not more than 5MB"
  var ALLOWED_EXT = ['pdf', 'doc', 'docx', 'rtf', 'txt'];

  var dropzone = document.getElementById('dropzone');
  var input = document.getElementById('file-input');
  var nameEl = document.getElementById('file-name');
  var finishBtn = document.getElementById('finish');
  var lastStepBtn = document.getElementById('last-step');

  var currentFile = null;

  /* ---------------- rendering ---------------- */

  function render(file) {
    currentFile = file || null;

    if (!currentFile) {
      nameEl.hidden = true;
      nameEl.textContent = '';
      dropzone.classList.remove('is-filled');
      finishBtn.removeAttribute('data-ready');
      return;
    }

    nameEl.hidden = false;
    nameEl.textContent = '✓ ' + currentFile.name + ' · ' + formatSize(currentFile.size);
    dropzone.classList.add('is-filled');
    finishBtn.setAttribute('data-ready', 'true');
  }

  function formatSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(0) + ' KB';
    return (bytes / 1024 / 1024).toFixed(1) + ' MB';
  }

  function fail(message) {
    nameEl.hidden = false;
    nameEl.textContent = message;
    nameEl.style.color = '#d64545';
    dropzone.classList.remove('is-filled');
    currentFile = null;
    window.setTimeout(function () { nameEl.style.color = ''; }, 2600);
  }

  /* ---------------- validation ---------------- */

  function accept(file) {
    if (!file) return;

    var ext = (file.name.split('.').pop() || '').toLowerCase();
    if (ALLOWED_EXT.indexOf(ext) === -1) {
      fail('Unsupported file type — please upload PDF, DOC, DOCX, RTF or TXT.');
      return;
    }
    if (file.size > MAX_BYTES) {
      fail('That file is ' + formatSize(file.size) + ' — the limit is 5MB.');
      return;
    }
    render(file);
  }

  /* ---------------- events ---------------- */

  input.addEventListener('change', function (e) {
    accept(e.target.files && e.target.files[0]);
  });

  // Keyboard parity: <label for> already forwards clicks, but not Enter/Space.
  dropzone.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      input.click();
    }
  });

  // Drag & drop. dragenter/dragleave fire per child element, so a counter is
  // needed -- toggling on every event makes the highlight flicker.
  var depth = 0;

  ['dragenter', 'dragover'].forEach(function (type) {
    dropzone.addEventListener(type, function (e) {
      e.preventDefault();
      e.stopPropagation();
      if (type === 'dragenter') depth++;
      dropzone.classList.add('is-dragover');
    });
  });

  ['dragleave', 'drop'].forEach(function (type) {
    dropzone.addEventListener(type, function (e) {
      e.preventDefault();
      e.stopPropagation();
      if (type === 'dragleave') depth = Math.max(0, depth - 1);
      else depth = 0;
      if (depth === 0) dropzone.classList.remove('is-dragover');
    });
  });

  dropzone.addEventListener('drop', function (e) {
    var dt = e.dataTransfer;
    if (dt && dt.files && dt.files.length) accept(dt.files[0]);
  });

  // Prevent the browser from navigating away when a file misses the dropzone.
  ['dragover', 'drop'].forEach(function (type) {
    window.addEventListener(type, function (e) { e.preventDefault(); });
  });

  /* ---------------- buttons ---------------- */

  finishBtn.addEventListener('click', function () {
    if (!currentFile) {
      fail('Please choose a file before finishing.');
      dropzone.classList.add('is-dragover');
      window.setTimeout(function () { dropzone.classList.remove('is-dragover'); }, 600);
      return;
    }
    // Demo only: no backend in this exercise.
    finishBtn.textContent = 'Uploading…';
    finishBtn.disabled = true;
    window.setTimeout(function () {
      finishBtn.textContent = 'Done ✓';
      window.setTimeout(function () {
        finishBtn.textContent = 'Finish';
        finishBtn.disabled = false;
      }, 1400);
    }, 900);
  });

  lastStepBtn.addEventListener('click', function () {
    // A real flow would navigate back; here we only prove the button is wired.
    lastStepBtn.textContent = 'Going back…';
    window.setTimeout(function () { lastStepBtn.textContent = 'Last step'; }, 900);
  });

  render(null);
})();
