// The house style for a landing page.
//
// Two behaviours, both opt-out rather than opt-in: the copy button on a
// command line tells you it worked, and sections come in when they scroll
// into view. With reduced motion they are simply there from the start.

(function () {
  'use strict';

  function setUpCopyButtons() {
    var buttons = document.querySelectorAll('[data-copy]');
    Array.prototype.forEach.call(buttons, function (button) {
      button.addEventListener('click', function () {
        var text = button.getAttribute('data-copy');
        var done = function () {
          var label = button.textContent;
          button.textContent = 'Скопировано';
          button.setAttribute('aria-live', 'polite');
          window.setTimeout(function () {
            button.textContent = label;
          }, 1400);
        };

        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(text).then(done, function () {});
          return;
        }

        // A page served over plain HTTP has no clipboard API. The old way
        // still works.
        var area = document.createElement('textarea');
        area.value = text;
        area.setAttribute('readonly', '');
        area.style.position = 'absolute';
        area.style.left = '-9999px';
        document.body.appendChild(area);
        area.select();
        try {
          document.execCommand('copy');
          done();
        } catch (error) {
          // Nothing to do: the text is on screen either way.
        }
        document.body.removeChild(area);
      });
    });
  }

  function setUpReveal() {
    var items = document.querySelectorAll('.reveal');
    if (!items.length) {
      return;
    }

    var reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
    if (reduced.matches || !('IntersectionObserver' in window)) {
      Array.prototype.forEach.call(items, function (item) {
        item.classList.add('is-visible');
      });
      return;
    }

    var observer = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            entry.target.classList.add('is-visible');
            observer.unobserve(entry.target);
          }
        });
      },
      { rootMargin: '0px 0px -10% 0px' }
    );

    Array.prototype.forEach.call(items, function (item) {
      observer.observe(item);
    });
  }

  function start() {
    setUpCopyButtons();
    setUpReveal();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
