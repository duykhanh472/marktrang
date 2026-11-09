/**
 * mark2web — reader.js
 *
 * Progressive Enhancement: Vanilla JavaScript reader enhancements.
 * - Feature-detected and try-catch-safe (no crashes on old browsers or Private Mode).
 * - Manages Theme, Font, Alignment, Settings Modal, and Chapter Progress.
 * - Operates entirely with localStorage (gracefully degrades if unavailable).
 *
 * Compatibility: ES5-compatible syntax for maximum browser support.
 * When JS is enabled, the <html> class is switched from "no-js" to "js"
 * by an inline script in <head> BEFORE this file is loaded.
 */

(function () {
    'use strict';

    // -------------------------------------------------------------------------
    // Safe Storage wrapper — prevents crashes in Private Mode / old browsers
    // -------------------------------------------------------------------------
    var storage = {
        get: function (key) {
            try {
                if (typeof window.localStorage !== 'undefined') {
                    return window.localStorage.getItem(key);
                }
            } catch (e) { /* SecurityError in some Private Mode configs */ }
            return null;
        },
        set: function (key, val) {
            try {
                if (typeof window.localStorage !== 'undefined') {
                    window.localStorage.setItem(key, val);
                }
            } catch (e) {}
        },
        getJSON: function (key) {
            try {
                var v = this.get(key);
                return v ? JSON.parse(v) : null;
            } catch (e) { return null; }
        },
        setJSON: function (key, val) {
            try { this.set(key, JSON.stringify(val)); } catch (e) {}
        }
    };

    // -------------------------------------------------------------------------
    // Theme / Font / Alignment — apply saved preferences immediately (anti-FOUC)
    // Called synchronously when the DOM is ready (this script is deferred/async
    // but placed at end of body — instant on modern; acceptable on legacy).
    // -------------------------------------------------------------------------
    var THEME_CLASSES = [
        'cool-dark-theme', 'warm-dark-theme', 'light-theme',
        'light-grid-theme', 'retro-dark-theme', 'black-theme'
    ];
    var FONT_CLASSES = [
        'monnaco-font', 'open-sans-font', 'pt-serif-font',
        'pt-sans-font', 'georgia-font', 'open-dyslexic-font'
    ];
    var ALIGN_CLASSES = ['middle-align', 'right-align'];

    function applyClass(classList, classes, value) {
        for (var i = 0; i < classes.length; i++) {
            classList.remove(classes[i]);
        }
        if (value) classList.add(value);
    }

    function restorePreferences() {
        var html = document.documentElement;
        var theme = storage.get('theme');
        var font  = storage.get('font');
        var align = storage.get('align');

        if (theme) applyClass(html.classList, THEME_CLASSES, theme + '-theme');
        if (font)  applyClass(html.classList, FONT_CLASSES,  font + '-font');
        if (align) applyClass(html.classList, ALIGN_CLASSES, align === 'left' ? '' : align + '-align');
    }

    restorePreferences();

    // -------------------------------------------------------------------------
    // DOM Ready helper (supports IE9+)
    // -------------------------------------------------------------------------
    function onReady(fn) {
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', fn);
        } else {
            fn();
        }
    }

    // -------------------------------------------------------------------------
    // Helper: query element(s)
    // -------------------------------------------------------------------------
    function $(sel, ctx) { return (ctx || document).querySelector(sel); }
    function $$(sel, ctx) {
        return Array.prototype.slice.call((ctx || document).querySelectorAll(sel));
    }

    onReady(function () {
        var html = document.documentElement;

        // -----------------------------------------------------------------------
        // Settings Modal
        // -----------------------------------------------------------------------
        var overlay          = $('#reader-overlay');
        var settingsContainer= $('#settings-container');
        var settingsOpen     = false;

        function openSettings() {
            settingsOpen = true;
            if (overlay)           overlay.classList.add('open');
            if (settingsContainer) settingsContainer.classList.add('open');
        }
        function closeSettings() {
            settingsOpen = false;
            if (overlay)           overlay.classList.remove('open');
            if (settingsContainer) settingsContainer.classList.remove('open');
        }

        // Icon triggers (settings gear)
        $$('.open-settings-btn').forEach(function (btn) {
            btn.addEventListener('click', function () {
                settingsOpen ? closeSettings() : openSettings();
            });
        });
        // Close via overlay click
        if (overlay) overlay.addEventListener('click', closeSettings);
        // Close button inside modal
        var closeBtn = $('#close-settings-btn');
        if (closeBtn) closeBtn.addEventListener('click', closeSettings);
        // Close on Escape key
        document.addEventListener('keydown', function (e) {
            if ((e.key === 'Escape' || e.keyCode === 27) && settingsOpen) closeSettings();
        });

        // Sync current selects to saved values
        var themeSelect = $('#select-theme');
        var fontSelect  = $('#select-font');
        var alignSelect = $('#select-align');
        if (themeSelect) themeSelect.value = storage.get('theme') || 'warm-dark';
        if (fontSelect)  fontSelect.value  = storage.get('font')  || 'open-sans';
        if (alignSelect) alignSelect.value = storage.get('align') || 'left';

        // Theme change
        if (themeSelect) {
            themeSelect.addEventListener('change', function () {
                var val = this.value;
                storage.set('theme', val);
                applyClass(html.classList, THEME_CLASSES, val + '-theme');
            });
        }
        // Font change
        if (fontSelect) {
            fontSelect.addEventListener('change', function () {
                var val = this.value;
                storage.set('font', val);
                applyClass(html.classList, FONT_CLASSES, val + '-font');
            });
        }
        // Alignment change
        if (alignSelect) {
            alignSelect.addEventListener('change', function () {
                var val = this.value;
                storage.set('align', val);
                applyClass(html.classList, ALIGN_CLASSES, val === 'left' ? '' : val + '-align');
            });
        }

        // -----------------------------------------------------------------------
        // Mobile Menu Drawer
        // -----------------------------------------------------------------------
        var menuToggle   = $('#mobile-menu-toggle');
        var menuDrawer   = $('#mobile-menu-drawer');
        var menuClose    = $('#mobile-menu-close');

        if (menuToggle && menuDrawer) {
            menuToggle.addEventListener('click', function () {
                var isOpen = menuDrawer.classList.contains('open');
                if (isOpen) menuDrawer.classList.remove('open');
                else        menuDrawer.classList.add('open');
            });
        }
        if (menuClose && menuDrawer) {
            menuClose.addEventListener('click', function () {
                menuDrawer.classList.remove('open');
            });
        }

        // -----------------------------------------------------------------------
        // Chapter Progress — Mark Done
        // -----------------------------------------------------------------------
        var STORAGE_KEY = 'completed_chapters';

        function getCompleted() {
            return storage.getJSON(STORAGE_KEY) || {};
        }
        function saveCompleted(obj) {
            storage.setJSON(STORAGE_KEY, obj);
        }

        function markChapterDone(chapterNum) {
            var completed = getCompleted();
            completed[String(chapterNum)] = true;
            saveCompleted(completed);
        }

        // Apply dots on side-nav for already-completed chapters
        function restoreDots() {
            var completed = getCompleted();
            $$('.side-nav .nav-chapter-link').forEach(function (link) {
                var num = link.getAttribute('data-chapter');
                if (num && completed[num]) {
                    // Add dot if not already there
                    if (!link.querySelector('.dot')) {
                        var dot = document.createElement('span');
                        dot.className = 'dot';
                        link.appendChild(dot);
                    }
                }
            });
        }
        restoreDots();

        // Handle "Mark Done" button on chapter page
        var markDoneBtn = $('.mark_done_button');
        if (markDoneBtn) {
            var chapterNum = markDoneBtn.getAttribute('data-chapter');
            var completed  = getCompleted();

            // Restore state if already marked
            if (chapterNum && completed[String(chapterNum)]) {
                markDoneBtn.textContent = 'Completed \u2713';
                markDoneBtn.classList.add('done');
            }

            markDoneBtn.addEventListener('click', function () {
                if (!chapterNum) return;
                markChapterDone(chapterNum);
                this.textContent = 'Completed \u2713';
                this.classList.add('done');

                // Update dot on current page's side-nav
                var currentLink = $('.side-nav [data-chapter="' + chapterNum + '"]');
                if (currentLink && !currentLink.querySelector('.dot')) {
                    var dot = document.createElement('span');
                    dot.className = 'dot';
                    currentLink.appendChild(dot);
                }
            });
        }
    });
})();
