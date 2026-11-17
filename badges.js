/*
 * - Connects the Ask page's badge controls to the shared badge picker.
 * - Exposes selected minor badges to ask.js when it submits a question.
 */
var askBadgePicker = window.BadgePicker.mount(document.getElementById("askForm"));
window.picked = askBadgePicker.getMinorTags();
askBadgePicker.onChange(function (selection) {
    window.picked = selection.minors;
});