/**
 * Floating Actions Hub
 * Controls the single bottom-right actions menu.
 */
(function () {
  'use strict';

  function getDock() {
    return document.getElementById('fabDock');
  }

  function getRoot() {
    return document.getElementById('unifiedActionsRoot');
  }

  function getButton() {
    return document.getElementById('unifiedActionsFab');
  }

  function getMenu() {
    return document.getElementById('unifiedActionsMenu');
  }

  function getUrl(name, fallback) {
    var dock = getDock();
    return (dock && dock.getAttribute(name)) || fallback;
  }

  function setOpen(open) {
    var root = getRoot();
    var button = getButton();
    var menu = getMenu();
    var dock = getDock();
    if (!root || !button || !menu) return;

    root.classList.toggle('is-open', open);
    menu.classList.toggle('hidden', !open);
    menu.setAttribute('aria-hidden', open ? 'false' : 'true');
    button.setAttribute('aria-expanded', open ? 'true' : 'false');
    if (dock) {
      dock.classList.toggle('fab-dock--menu-open', open);
    }
  }

  function close() {
    setOpen(false);
  }

  function toggle() {
    var root = getRoot();
    if (!root) return;
    setOpen(!root.classList.contains('is-open'));
  }

  function startTimer() {
    close();
    var startButton = document.querySelector('#openStartTimer');
    if (startButton) {
      startButton.click();
      return;
    }

    var dashboard = getUrl('data-dashboard-url', '/');
    window.location.href = dashboard.split('#')[0] + '#start-timer';
  }

  function navigateTo(attr, fallback) {
    close();
    window.location.href = getUrl(attr, fallback);
  }

  function runAction(action) {
    if (action === 'start') {
      startTimer();
    } else if (action === 'log') {
      navigateTo('data-manual-entry-url', '/timer/manual_entry');
    } else if (action === 'task') {
      navigateTo('data-new-task-url', '/tasks/create');
    } else if (action === 'project') {
      navigateTo('data-new-project-url', '/projects/create');
    } else if (action === 'client') {
      navigateTo('data-new-client-url', '/clients/create');
    } else if (action === 'reports') {
      navigateTo('data-reports-url', '/reports/');
    }
  }

  document.addEventListener('DOMContentLoaded', function () {
    var root = getRoot();
    var button = getButton();
    var menu = getMenu();
    if (!root || !button || !menu) return;

    button.addEventListener('click', function (event) {
      event.stopPropagation();
      toggle();
    });

    menu.querySelectorAll('[data-action]').forEach(function (item) {
      item.addEventListener('click', function () {
        runAction(item.getAttribute('data-action'));
      });
    });

    document.addEventListener('click', function (event) {
      if (!root.classList.contains('is-open')) return;
      if (root.contains(event.target)) return;
      close();
    });

    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && root.classList.contains('is-open')) {
        close();
        button.focus();
      }
    });
  });
})();
