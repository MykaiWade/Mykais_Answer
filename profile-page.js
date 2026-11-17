/*
 * - Handles profile QR sharing, camera scanning, contacts, and profile verification.
 * - Loaded by profile.html; calls the profile, contact, and verification APIs in server.py.
 * - Uses qr-scanner.umd.min.js to decode camera frames on this device.
 */
(function () {
    var params = new URLSearchParams(window.location.search);
    var memberId = params.get("member") || params.get("scan");
    var scanId = params.get("scan");
    var sharePanel = document.getElementById("shareProfilePanel");
    var showQrButton = document.getElementById("showProfileQrButton");
    var shareQrImage = document.getElementById("shareProfileQrImage");
    var publicPanel = document.getElementById("publicProfilePanel");
    var publicName = document.getElementById("publicProfileName");
    var publicStatus = document.getElementById("publicProfileStatus");
    var addContactButton = document.getElementById("addContactButton");
    var verificationPrompt = document.getElementById("verificationPrompt");
    var verifyButton = document.getElementById("verifyScannedMemberButton");
    var contactsPanel = document.getElementById("contactsPanel");
    var contactsStatus = document.getElementById("contactsStatus");
    var incomingList = document.getElementById("incomingContactRequests");
    var outgoingList = document.getElementById("outgoingContactRequests");
    var contactList = document.getElementById("contactList");
    var openScannerButton = document.getElementById("openQrScannerButton");
    var stopScannerButton = document.getElementById("stopQrScannerButton");
    var scannerStatus = document.getElementById("scannerStatus");
    var scannerPanel = document.getElementById("qrScannerPanel");
    var video = document.getElementById("qrScannerVideo");
    var currentProfile = null;
    var targetProfile = null;
    var shareQrUrl = null;
    var qrScanner = null;
    var scanConnectStarted = false;

    function fetchJson(url, options) {
        return fetch(url, options).then(function (response) {
            return response.json().then(function (data) {
                if (!response.ok) {
                    throw new Error(data.detail || "The profile request failed.");
                }
                return data;
            });
        });
    }

    function memberLabel(member) {
        var label = member.real_name;
        if (member.account_number !== null && member.account_number !== undefined) {
            label += " " + member.account_number;
        }
        return label + (member.verified ? " # — Verified" : " — Unverified");
    }

    function contactLink(member) {
        var link = document.createElement("a");
        link.href = "profile.html?member=" + encodeURIComponent(member.public_id);
        link.textContent = memberLabel(member);
        return link;
    }

    function renderList(list, members, emptyMessage) {
        list.replaceChildren();
        if (!members.length) {
            var empty = document.createElement("li");
            empty.textContent = emptyMessage;
            list.appendChild(empty);
            return;
        }
        members.forEach(function (member) {
            var item = document.createElement("li");
            item.appendChild(contactLink(member));
            list.appendChild(item);
        });
    }

    // Load the signed-in member's private contacts, requests, and accept/decline actions.
    function loadContacts() {
        if (!currentProfile) {
            contactsPanel.hidden = true;
            return Promise.resolve();
        }
        contactsPanel.hidden = false;
        contactsStatus.textContent = "Loading your contacts...";
        return fetchJson("/api/contacts")
            .then(function (data) {
                renderList(contactList, data.contacts, "You have no contacts yet.");
                renderList(outgoingList, data.outgoing, "No pending requests.");
                incomingList.replaceChildren();
                if (!data.incoming.length) {
                    var empty = document.createElement("li");
                    empty.textContent = "No pending contact requests.";
                    incomingList.appendChild(empty);
                }
                data.incoming.forEach(function (member) {
                    var item = document.createElement("li");
                    item.appendChild(contactLink(member));
                    ["accept", "decline"].forEach(function (action) {
                        var button = document.createElement("button");
                        button.type = "button";
                        button.textContent = action === "accept" ? "Accept" : "Decline";
                        button.addEventListener("click", function () {
                            button.disabled = true;
                            fetchJson(
                                "/api/contacts/requests/" + member.id + "/" + action,
                                { method: "POST" }
                            )
                                .then(function (result) {
                                    contactsStatus.textContent = result.message;
                                    return loadContacts();
                                })
                                .catch(function (error) {
                                    contactsStatus.textContent = error.message;
                                    button.disabled = false;
                                });
                        });
                        item.appendChild(button);
                    });
                    incomingList.appendChild(item);
                });
                contactsStatus.textContent = "Contact lists are private to each account.";
            })
            .catch(function (error) {
                contactsStatus.textContent = error.message;
            });
    }

    // Add a contact from a profile page; the server creates the connection for both members.
    function addContact() {
        if (!currentProfile || !memberId || !targetProfile) {
            return Promise.resolve();
        }
        if (targetProfile.relationship === "self") {
            publicStatus.textContent = "This is your own profile.";
            return Promise.resolve();
        }
        addContactButton.disabled = true;
        return fetchJson("/api/contacts", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ public_id: memberId })
        })
            .then(function (result) {
                publicStatus.textContent = result.message;
                addContactButton.hidden = true;
                return Promise.all([refreshPublicProfile(), loadContacts()]);
            })
            .catch(function (error) {
                publicStatus.textContent = error.message;
                addContactButton.disabled = false;
            });
    }

    // Visiting a profile through a scanned QR adds it without requiring another button press.
    function connectScannedMember() {
        if (!scanId || scanConnectStarted || !currentProfile || !targetProfile) {
            return Promise.resolve();
        }
        if (targetProfile.relationship === "self") {
            scanConnectStarted = true;
            publicStatus.textContent = "This is your own profile.";
            return Promise.resolve();
        }
        scanConnectStarted = true;
        return fetchJson("/api/contacts", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ public_id: scanId })
        })
            .then(function (result) {
                publicStatus.textContent = result.message;
                return Promise.all([refreshPublicProfile(), loadContacts()]);
            })
            .catch(function (error) {
                publicStatus.textContent = error.message;
                addContactButton.hidden = false;
            });
    }

    function refreshPublicProfile() {
        if (!memberId) {
            publicPanel.hidden = true;
            return Promise.resolve();
        }
        publicPanel.hidden = false;
        publicName.textContent = "Loading member profile...";
        publicStatus.textContent = "";
        addContactButton.hidden = true;
        verifyButton.hidden = true;
        verificationPrompt.hidden = true;
        return fetchJson("/api/public-profile/" + encodeURIComponent(memberId))
            .then(function (member) {
                targetProfile = member;
                publicName.textContent = memberLabel(member);
                if (member.relationship === "signed_out") {
                    publicStatus.textContent = "Sign in to add this member to your contacts.";
                } else if (member.relationship === "self") {
                    publicStatus.textContent = "This is your profile.";
                } else if (member.relationship === "connected") {
                    publicStatus.textContent = "You are already contacts.";
                } else {
                    publicStatus.textContent = "Add this member to your contacts.";
                    addContactButton.hidden = false;
                }
                if (member.can_verify) {
                    verificationPrompt.hidden = false;
                    verifyButton.hidden = false;
                }
            })
            .catch(function (error) {
                targetProfile = null;
                publicName.textContent = "";
                publicStatus.textContent = error.message;
            });
    }

    // Stop the local camera stream as soon as scanning ends or the page is left.
    function stopCamera() {
        if (qrScanner) {
            qrScanner.destroy();
            qrScanner = null;
        }
        video.srcObject = null;
        scannerPanel.hidden = true;
    }

    // Accept only this site's profile or verification links from scanned QR codes.
    function handleScannedValue(value) {
        var scannedUrl;
        try {
            scannedUrl = new URL(value);
        } catch (error) {
            scannerStatus.textContent = "That QR code is not a valid profile link.";
            return;
        }
        var profilePath = new URL("profile.html", window.location.href).pathname;
        var verificationPath = new URL("verify.html", window.location.href).pathname;
        if (scannedUrl.origin !== window.location.origin) {
            scannerStatus.textContent = "Scan a Mykai's Answer profile QR code.";
            return;
        }
        if (scannedUrl.pathname === verificationPath && scannedUrl.hash.length > 1) {
            window.location.href = scannedUrl.pathname + scannedUrl.search + scannedUrl.hash;
            return;
        }
        var scannedMemberId = scannedUrl.searchParams.get("scan")
            || scannedUrl.searchParams.get("member");
        if (scannedUrl.pathname !== profilePath || !scannedMemberId) {
            scannerStatus.textContent = "Scan a Mykai's Answer profile QR code.";
            return;
        }
        window.location.href = scannedUrl.pathname + "?scan="
            + encodeURIComponent(scannedMemberId);
    }

    // Start the local QR decoder after checking browser security and camera support.
    openScannerButton.addEventListener("click", function () {
        scannerStatus.textContent = "";
        if (!window.isSecureContext) {
            scannerStatus.textContent = "Camera access requires HTTPS or localhost.";
            return;
        }
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            scannerStatus.textContent = "This browser does not provide camera access. Use its Camera app to scan instead.";
            return;
        }
        if (!window.QrScanner) {
            scannerStatus.textContent = "The in-page QR scanner could not be loaded. Refresh the page and try again.";
            return;
        }
        openScannerButton.disabled = true;
        scannerPanel.hidden = false;
        qrScanner = new window.QrScanner(
            video,
            function (result) {
                var value = typeof result === "string" ? result : result.data;
                stopCamera();
                scannerStatus.textContent = "QR code scanned. Opening profile...";
                handleScannedValue(value);
            },
            {
                preferredCamera: "environment",
                maxScansPerSecond: 8,
                returnDetailedScanResult: true
            }
        );
        qrScanner.start()
            .then(function () {
                scannerStatus.textContent = "Point the camera at a profile QR code.";
            })
            .catch(function (error) {
                stopCamera();
                if (error.name === "NotAllowedError" || error.name === "SecurityError") {
                    scannerStatus.textContent = "Allow camera access in your browser settings, then try again.";
                } else {
                    scannerStatus.textContent = "Could not start the QR scanner: " + error.message;
                }
            })
            .finally(function () {
                openScannerButton.disabled = false;
            });
    });

    stopScannerButton.addEventListener("click", stopCamera);

    // Request the signed-in member's own QR image from the server when it is shown.
    showQrButton.addEventListener("click", function () {
        if (!shareQrImage.hidden) {
            shareQrImage.hidden = true;
            showQrButton.textContent = "Show my QR code";
            return;
        }
        showQrButton.disabled = true;
        fetch("/api/profile/qr")
            .then(function (response) {
                if (!response.ok) {
                    return response.json().then(function (data) {
                        throw new Error(data.detail || "Your profile QR could not be loaded.");
                    });
                }
                return response.blob();
            })
            .then(function (image) {
                if (shareQrUrl) {
                    URL.revokeObjectURL(shareQrUrl);
                }
                shareQrUrl = URL.createObjectURL(image);
                shareQrImage.src = shareQrUrl;
                shareQrImage.hidden = false;
                showQrButton.textContent = "Hide my QR code";
            })
            .catch(function (error) {
                contactsStatus.textContent = error.message;
            })
            .finally(function () {
                showQrButton.disabled = false;
            });
    });

    addContactButton.addEventListener("click", addContact);

    // Verification is a separate, explicit action available only when the server allows it.
    verifyButton.addEventListener("click", function () {
        if (!targetProfile || !targetProfile.can_verify || !memberId) {
            return;
        }
        verifyButton.disabled = true;
        fetchJson("/api/verification/approve-profile", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ public_id: memberId })
        })
            .then(function (result) {
                publicStatus.textContent = result.message;
                return Promise.all([refreshPublicProfile(), loadContacts()]);
            })
            .catch(function (error) {
                publicStatus.textContent = error.message;
            })
            .finally(function () {
                verifyButton.disabled = false;
            });
    });

    // Keep the QR, contacts, and scanned-profile view in sync with account sign-in changes.
    function updateProfile(profile) {
        currentProfile = profile;
        sharePanel.hidden = !profile;
        contactsPanel.hidden = !profile;
        if (!profile) {
            shareQrImage.hidden = true;
            shareQrImage.removeAttribute("src");
            if (shareQrUrl) {
                URL.revokeObjectURL(shareQrUrl);
                shareQrUrl = null;
            }
            showQrButton.textContent = "Show my QR code";
        }
        refreshPublicProfile().then(connectScannedMember);
        loadContacts();
    }

    window.addEventListener("profilechange", function (event) {
        updateProfile(event.detail);
    });
    window.addEventListener("pagehide", stopCamera);
    window.SiteProfile.ready.then(updateProfile);
})();
