/* badges.js: the major and minor badge menus for ask.html.
   The list of badges lives in badges.txt (one line per major: MATH: CALCULUS, ALGEBRA).
   Watch for: the page needs elements with ids major, minorRow, minor, and picked, or this script does nothing. */

/* ---------- BADGES ---------- */

var badges = {};   /* Filled from badges.txt, like { MATH: ["CALCULUS", "ALGEBRA"] }. */
var picked = [];   /* The minor badges chosen so far. */
var majorMenu = document.getElementById("major");   /* The first menu. */
var minorMenu = document.getElementById("minor");   /* The second menu. */

/* Shows the picked minor badges as small buttons. Clicking one removes it. */
function drawPicked() {
    var box = document.getElementById("picked");
    box.innerHTML = "";   /* Clear the old buttons first. */
    picked.forEach(function (name) {
        var b = document.createElement("button");
        b.type = "button";   /* Keeps the button from submitting the form. */
        b.textContent = name + " \u00d7";   /* The word plus an x. */
        b.onclick = function () {   /* Clicking removes this badge. */
            picked = picked.filter(function (n) { return n !== name; });
            drawPicked();
        };
        box.appendChild(b);
    });
}

/* Read badges.txt. Each line looks like  MATH: CALCULUS, ALGEBRA */
fetch("/badges.txt", { cache: "no-store" })
    .then(function (r) {
        if (!r.ok) { throw new Error("missing"); }   /* File not found. */
        return r.text();
    })
    .then(function (text) {
        text.split("\n").forEach(function (line) {
            if (line.trim().charAt(0) === "#") { return; }   /* Skips # note lines, since some contain colons and would show up as fake majors. */
            var parts = line.split(":");   /* Splits at the colon. */
            if (parts.length < 2) { return; }   /* Skips blank lines. */
            var major = parts[0].trim().toUpperCase();   /* The word before the colon. */
            badges[major] = parts[1].split(",").map(function (n) { return n.trim().toUpperCase(); }).filter(Boolean);   /* The words after it. */
            majorMenu.appendChild(new Option(major, major));   /* Adds the major to the first menu. */
        });
    })
    .catch(function () { majorMenu.options[0].textContent = "Badges couldn't load."; });   /* CHANGE: the wording. */

/* When a major badge is picked: clear old picks and fill the second menu. */
majorMenu.onchange = function () {
    picked = [];   /* Minor badges belong to one major, so start over. */
    drawPicked();
    var list = badges[majorMenu.value];   /* The minors for this major, or nothing. */
    document.getElementById("minorRow").style.display = list ? "" : "none";   /* Show or hide the second menu. */
    minorMenu.innerHTML = "<option value=''>Add a minor badge</option>";   /* The starting text. */
    (list || []).forEach(function (n) { minorMenu.appendChild(new Option(n, n)); });
};

/* When a minor badge is picked: add it once, then reset the menu. */
minorMenu.onchange = function () {
    if (minorMenu.value && picked.indexOf(minorMenu.value) === -1) {
        picked.push(minorMenu.value);
        drawPicked();
    }
    minorMenu.value = "";   /* Back to "Add a minor badge". */
};

/* ---------- END OF BADGES ---------- */