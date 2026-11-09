/*
 * Keyboard shortcuts for scoring words, shared by the test pages
 * (quick.html, azbio_mandarin.html, ...) and the rater page (review.html).
 *
 *   1 2 ... 9 0 - =   flip word 1 ... 12 between correct and wrong
 *                     (an unscored word becomes correct on the first press)
 *   A                 mark every word correct  (same as the "All" button)
 *   N                 mark every word wrong    (same as the "None" button)
 *   Space             press the play / record button
 *   Enter             go to the next audio, once every word is scored
 *   U                 toggle "unclear" (rater page only)
 *   ?                 show or hide this list
 *
 * The file only reads and clicks elements that are already on the page, so
 * pages that do not load it behave exactly as before.
 */
(function () {
  "use strict";

  const WORD_KEYS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "-", "="];

  // Map from KeyboardEvent.code, so shortcuts still work with a Chinese
  // input method or a non-US keyboard layout.
  const CODE_TO_KEY = {
    Digit1: "1", Digit2: "2", Digit3: "3", Digit4: "4", Digit5: "5",
    Digit6: "6", Digit7: "7", Digit8: "8", Digit9: "9", Digit0: "0",
    Numpad1: "1", Numpad2: "2", Numpad3: "3", Numpad4: "4", Numpad5: "5",
    Numpad6: "6", Numpad7: "7", Numpad8: "8", Numpad9: "9", Numpad0: "0",
    Minus: "-", Equal: "=", KeyA: "a", KeyN: "n", KeyU: "u",
    Space: " ", Enter: "enter", NumpadEnter: "enter", Slash: "?",
  };

  function keyOf(event) {
    if (event.code in CODE_TO_KEY) return CODE_TO_KEY[event.code];
    if (event.key === "?") return "?";
    return null;
  }

  function isTyping(target) {
    if (!target || !target.tagName) return false;
    const tag = target.tagName.toLowerCase();
    if (tag === "textarea" || tag === "select" || target.isContentEditable) {
      return true;
    }
    if (tag === "input") {
      const type = (target.getAttribute("type") || "text").toLowerCase();
      return !["radio", "checkbox", "button", "submit", "reset"].includes(type);
    }
    return false;
  }

  function wordGroups() {
    const holder = document.querySelector(".options-case");
    if (!holder) return [];
    return Array.from(holder.children).filter(
      (w) => w.querySelector(".annotation-on"));
  }

  /** Flip one word: unscored or wrong -> correct, correct -> wrong. */
  function toggleWord(index) {
    const group = wordGroups()[index];
    if (!group) return false;
    const on = group.querySelector(".annotation-on");
    const off = group.querySelector(".annotation-off");
    // click() checks the radio and fires the same input/change events a
    // mouse click would, so the pages' own listeners update as usual.
    (on.checked ? off : on).click();
    return true;
  }

  function clickIfUsable(selector) {
    const el = document.querySelector(selector);
    if (!el || el.disabled || el.classList.contains("hidden")) return false;
    el.click();
    return true;
  }

  function allWordsScored() {
    return wordGroups().every(
      (g) => Array.from(g.querySelectorAll(".annotation")).some((r) => r.checked));
  }

  function goNext() {
    const form = document.getElementById("interactive");
    if (form && !form.checkValidity()) return false;
    if (!allWordsScored()) return false;
    return clickIfUsable("#next-audio");
  }

  /** Put the key name on each word, so the rater sees which key to press. */
  function labelWords() {
    wordGroups().forEach((group, i) => {
      const key = WORD_KEYS[i];
      group.querySelectorAll(".option").forEach((label) => {
        if (key === undefined) {
          label.removeAttribute("data-shortcut");
        } else {
          label.setAttribute("data-shortcut", key);
        }
      });
    });
  }

  function addHelp() {
    if (document.getElementById("shortcut-help")) return;
    const anchor = document.getElementById("result-options");
    if (!anchor) return;
    const help = document.createElement("div");
    help.id = "shortcut-help";
    help.innerHTML =
      "<b>Keys</b>: <kbd>1</kbd>–<kbd>9</kbd> <kbd>0</kbd> <kbd>-</kbd> " +
      "<kbd>=</kbd> flip word &nbsp;·&nbsp; <kbd>A</kbd> all &nbsp;·&nbsp; " +
      "<kbd>N</kbd> none &nbsp;·&nbsp; <kbd>Space</kbd> play &nbsp;·&nbsp; " +
      "<kbd>Enter</kbd> next" +
      (document.getElementById("unclear-checkbox")
        ? " &nbsp;·&nbsp; <kbd>U</kbd> unclear" : "") +
      " &nbsp;·&nbsp; <kbd>?</kbd> hide";
    anchor.insertAdjacentElement("afterend", help);
  }

  function addStyle() {
    if (document.getElementById("shortcut-style")) return;
    const style = document.createElement("style");
    style.id = "shortcut-style";
    style.textContent = `
      .option[data-shortcut]::before {
        content: attr(data-shortcut);
        display: inline-block;
        min-width: 1.2em;
        margin-right: 0.5em;
        padding: 0 0.25em;
        border-radius: 0.25em;
        font-size: 0.7em;
        vertical-align: middle;
        background: rgba(255, 255, 255, 0.85);
        color: #333;
      }
      body.shortcuts-hidden .option[data-shortcut]::before { display: none; }
      #shortcut-help {
        order: 2;
        max-width: 24rem;
        margin: 0.5em auto;
        line-height: 1.6;
        font-family: var(--compact, sans-serif);
        font-size: 0.85rem;
        text-align: center;
        opacity: 0.8;
      }
      body.shortcuts-hidden #shortcut-help { display: none; }
      #shortcut-help kbd {
        border: 1px solid #aaa;
        border-radius: 0.2em;
        padding: 0 0.3em;
        font-family: inherit;
      }`;
    document.head.appendChild(style);
  }

  function handleKey(event) {
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    if (isTyping(event.target)) return;
    const key = keyOf(event);
    if (key === null) return;
    // Holding a key down should not flip a word back and forth.
    if (event.repeat && key !== " ") {
      event.preventDefault();
      return;
    }

    let handled = false;
    const wordIndex = WORD_KEYS.indexOf(key);
    if (wordIndex >= 0 && !event.shiftKey) {
      handled = toggleWord(wordIndex);
    } else if (key === "a") {
      handled = clickIfUsable("#result-all");
    } else if (key === "n") {
      handled = clickIfUsable("#result-none");
    } else if (key === " ") {
      handled = event.repeat || clickIfUsable("#playback");
    } else if (key === "enter") {
      handled = goNext();
    } else if (key === "u") {
      handled = clickIfUsable("#unclear-checkbox");
    } else if (key === "?") {
      document.body.classList.toggle("shortcuts-hidden");
      handled = true;
    }
    if (handled || key === " ") {
      // Stop Space from also pressing whatever button has focus.
      event.preventDefault();
    }
  }

  function start() {
    addStyle();
    addHelp();
    labelWords();
    // The pages rebuild the word buttons for every sentence.
    new MutationObserver(labelWords).observe(document.body, {
      childList: true, subtree: true,
    });
    document.addEventListener("keydown", handleKey);
  }

  // Exposed for tests.
  window.ScoringKeys = { WORD_KEYS, toggleWord, goNext, labelWords };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
