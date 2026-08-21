// Adds a "Copy" button to every fenced code block on the docs site.
// Hooks `div.highlighter-rouge` (the Rouge block wrapper). Inline code is a
// bare <code> with the same class, so the `div.` qualifier excludes it.
(function () {
  var COPY_ICON =
    '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="square" stroke-linejoin="miter" aria-hidden="true"><rect x="9" y="9" width="12" height="12"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>';
  var CHECK_ICON =
    '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="square" stroke-linejoin="miter" aria-hidden="true"><polyline points="20 6 9 17 4 12"></polyline></svg>';

  function codeText(block) {
    var code = block.querySelector('pre code') || block.querySelector('pre');
    var text = code ? code.innerText : block.innerText;
    return text.replace(/\n+$/, '');
  }

  function fallbackCopy(text) {
    var ta = document.createElement('textarea');
    ta.value = text;
    ta.setAttribute('readonly', '');
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    try {
      document.execCommand('copy');
    } catch (e) {
      /* no-op */
    }
    document.body.removeChild(ta);
  }

  function attach(block) {
    if (block.dataset.copyAttached) return;
    block.dataset.copyAttached = 'true';

    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'copy-code-button';
    btn.innerHTML = COPY_ICON;
    btn.setAttribute('aria-label', 'Copy code to clipboard');
    btn.setAttribute('title', 'Copy');

    var resetTimer;
    btn.addEventListener('click', function () {
      var text = codeText(block);
      var markCopied = function () {
        btn.innerHTML = CHECK_ICON;
        btn.classList.add('is-copied');
        btn.setAttribute('title', 'Copied');
        clearTimeout(resetTimer);
        resetTimer = setTimeout(function () {
          btn.innerHTML = COPY_ICON;
          btn.classList.remove('is-copied');
          btn.setAttribute('title', 'Copy');
        }, 2000);
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(markCopied, function () {
          fallbackCopy(text);
          markCopied();
        });
      } else {
        fallbackCopy(text);
        markCopied();
      }
    });

    block.appendChild(btn);
  }

  function init() {
    var blocks = document.querySelectorAll('div.highlighter-rouge');
    Array.prototype.forEach.call(blocks, attach);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
