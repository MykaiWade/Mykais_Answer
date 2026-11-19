(function () {
    var inactivityLimit = 5 * 60 * 1000;
    var reportInterval = 30 * 1000;
    var lastInteraction = Date.now();
    var lastReportedInteraction = 0;
    var lastReportAt = 0;
    var offlineTimer = null;

    function setPresence(online) {
        if (offlineTimer !== null) {
            window.clearTimeout(offlineTimer);
            offlineTimer = null;
        }
        window.dispatchEvent(new CustomEvent("presencechange", {
            detail: { online: online }
        }));
        if (online) {
            offlineTimer = window.setTimeout(function () {
                setPresence(false);
            }, inactivityLimit);
        }
    }

    function reportActivity(force) {
        if (document.visibilityState === "hidden"
                || lastInteraction <= lastReportedInteraction) {
            return;
        }
        var now = Date.now();
        if (!force && now - lastReportAt < reportInterval) {
            return;
        }
        var reportedInteraction = lastInteraction;
        lastReportedInteraction = reportedInteraction;
        lastReportAt = now;

        fetch("/api/activity", { method: "POST" })
            .then(function (response) {
                return response.json().then(function (data) {
                    if (!response.ok) {
                        throw new Error(data.detail || "Online status could not be updated.");
                    }
                    return data;
                });
            })
            .then(function (data) {
                setPresence(Boolean(data.online));
            })
            .catch(function (error) {
                console.error("Could not update online status:", error);
            });
    }

    function noteActivity() {
        lastInteraction = Date.now();
        reportActivity(false);
    }

    ["pointerdown", "pointermove", "keydown", "scroll", "touchstart"].forEach(
        function (eventName) {
            document.addEventListener(eventName, noteActivity, { passive: true });
        }
    );
    document.addEventListener("visibilitychange", function () {
        if (document.visibilityState === "visible") {
            lastInteraction = Date.now();
            reportActivity(true);
        }
    });

    reportActivity(true);
    window.setInterval(function () {
        reportActivity(false);
    }, 15 * 1000);
})();
