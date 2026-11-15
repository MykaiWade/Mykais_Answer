/*
 * - Loads badge categories from badges.txt and mounts reusable major/minor selectors.
 * - Used by badges.js, chat.js, and rooms.js to keep badge choices consistent across pages.
 */
(function () {
    var badgeCatalog = Object.create(null);
    var catalogReady = fetch("/badges.txt", { cache: "no-store" })
        // Resolve the public badge list beside each page so GitHub project paths work too.
        var catalogReady = fetch("badges.txt", { cache: "no-store" })
        .then(function (response) {
            if (!response.ok) {
                throw new Error("Badge list could not be loaded.");
            }
            return response.text();
        })
        .then(function (text) {
            text.split("\n").forEach(function (line) {
                if (!line.trim() || line.trim().charAt(0) === "#") {
                    return;
                }
                var parts = line.split(":");
                if (parts.length < 2) {
                    return;
                }
                var major = parts[0].trim().toUpperCase();
                badgeCatalog[major] = parts[1].split(",")
                    .map(function (badge) { return badge.trim().toUpperCase(); })
                    .filter(Boolean);
            });
            return badgeCatalog;
        })
        .catch(function () {
            return badgeCatalog;
        });

    // Mounts one major/minor picker and exposes its current selection to the owning page.
    function mount(root) {
        var majorMenu = root.querySelector("[data-badge-major]");
        var minorRow = root.querySelector("[data-badge-minor-row]");
        var minorMenu = root.querySelector("[data-badge-minor]");
        var pickedBox = root.querySelector("[data-badge-picked]");
        var selectedMinors = [];
        var listeners = [];

        // Keeps the visible minor badges and all page listeners in sync with this picker.
        function updateSelection() {
            window.picked = selectedMinors.slice();
            pickedBox.innerHTML = "";
            selectedMinors.forEach(function (badge) {
                var tag = document.createElement("span");
                tag.className = "tag";
                tag.appendChild(document.createTextNode(badge + " "));

                var removeButton = document.createElement("button");
                removeButton.type = "button";
                removeButton.textContent = "x";
                removeButton.setAttribute("aria-label", "Remove " + badge + " badge");
                removeButton.addEventListener("click", function () {
                    selectedMinors = selectedMinors.filter(function (item) {
                        return item !== badge;
                    });
                    updateSelection();
                });
                tag.appendChild(removeButton);
                pickedBox.appendChild(tag);
            });

            listeners.forEach(function (listener) {
                listener({ major: majorMenu.value, minors: selectedMinors.slice() });
            });
        }

        // Loads the shared catalog into this picker's major menu.
        catalogReady.then(function (catalog) {
            if (!Object.keys(catalog).length) {
                majorMenu.options[0].textContent = "Badges could not load.";
                return;
            }
            Object.keys(catalog).forEach(function (major) {
                majorMenu.appendChild(new Option(major, major));
            });
        });

        // Changing the major clears old minors because minor badges belong to one major.
        majorMenu.addEventListener("change", function () {
            selectedMinors = [];
            minorMenu.innerHTML = "<option value=''>Add a minor badge</option>";
            var minors = badgeCatalog[majorMenu.value] || [];
            minorRow.hidden = !minors.length;
            minors.forEach(function (badge) {
                minorMenu.appendChild(new Option(badge, badge));
            });
            updateSelection();
        });

        // Adds each chosen minor once, then returns the menu to its prompt.
        minorMenu.addEventListener("change", function () {
            if (minorMenu.value && selectedMinors.indexOf(minorMenu.value) === -1) {
                selectedMinors.push(minorMenu.value);
                updateSelection();
            }
            minorMenu.value = "";
        });

        return {
            getMajor: function () { return majorMenu.value; },
            getMinorTags: function () { return selectedMinors.slice(); },
            getTags: function () {
                return majorMenu.value ? [majorMenu.value].concat(selectedMinors) : [];
            },
            onChange: function (listener) { listeners.push(listener); }
        };
    }

    window.BadgePicker = { ready: catalogReady, mount: mount };
})();